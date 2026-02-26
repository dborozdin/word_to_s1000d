/**
 * pdf-overlay.js — PDF page overlay creation and text block analysis.
 *
 * Creates visual annotation markers on PDF page wrappers by analyzing
 * text content from pdf.js or server-side PyMuPDF blocks.
 */

import { ANNO_TYPE_LABELS } from './config.js';
import { dom } from './state.js';
import * as state from './state.js';
import { normType } from './utils.js';
import { getAnnoColor, recalcMaxIdx, updatePosition } from './badges.js';
import { syncPdfMarkers } from './pdf-sync.js';
import { makeNavHandler } from './navigation.js';

/**
 * Analyze pdf.js textContent items and group them into logical blocks.
 * Returns array of {type, yTopPct, yBottomPct, text}.
 */
export function analyzePdfTextContent(textContent, viewport) {
    var items = textContent.items;
    if (!items || items.length === 0) return [];

    var vpHeight = viewport.height;
    var vpScale = viewport.scale;

    // 1. Extract items with coordinates (convert PDF space -> viewport pixels)
    var textItems = [];
    for (var i = 0; i < items.length; i++) {
        var item = items[i];
        if (!item.str || item.str.trim() === '') continue;

        var tx = item.transform;
        // tx = [scaleX, skewX, skewY, scaleY, translateX, translateY] in PDF user-space
        var fontSizePdf = Math.abs(tx[3]) || Math.abs(tx[0]) || 12;
        var fontSize = fontSizePdf * vpScale;

        // Convert PDF coordinates (origin bottom-left) to viewport pixels (origin top-left)
        var pt = viewport.convertToViewportPoint(tx[4], tx[5]);
        var x = pt[0];
        var y = pt[1];

        textItems.push({
            str: item.str,
            x: x,
            y: y,
            fontSize: fontSize,
            width: (item.width || 0) * vpScale
        });
    }

    if (textItems.length === 0) return [];

    // 2. Sort by Y position (top to bottom), then X (left to right)
    textItems.sort(function (a, b) {
        var dy = a.y - b.y;
        if (Math.abs(dy) > 2) return dy;
        return a.x - b.x;
    });

    // 3. Group into lines (items with similar Y)
    var lines = [];
    var currentLine = [textItems[0]];
    for (var i = 1; i < textItems.length; i++) {
        var prev = currentLine[currentLine.length - 1];
        var curr = textItems[i];
        var lineThreshold = Math.max(prev.fontSize, curr.fontSize) * 0.6;
        if (Math.abs(curr.y - prev.y) <= lineThreshold) {
            currentLine.push(curr);
        } else {
            lines.push(currentLine);
            currentLine = [curr];
        }
    }
    lines.push(currentLine);

    // 4. Compute line properties
    var lineInfos = [];
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        var text = '';
        var maxFontSize = 0;
        var minX = Infinity;
        var avgY = 0;
        var xPositions = [];

        for (var j = 0; j < line.length; j++) {
            text += (j > 0 ? ' ' : '') + line[j].str;
            if (line[j].fontSize > maxFontSize) maxFontSize = line[j].fontSize;
            if (line[j].x < minX) minX = line[j].x;
            avgY += line[j].y;
            xPositions.push(line[j].x);
        }
        avgY /= line.length;

        lineInfos.push({
            text: text.trim(),
            fontSize: maxFontSize,
            y: avgY,
            x: minX,
            itemCount: line.length,
            xPositions: xPositions
        });
    }

    // 5. Compute median font size for classification
    var fontSizes = lineInfos.map(function (l) { return l.fontSize; });
    fontSizes.sort(function (a, b) { return a - b; });
    var medianFontSize = fontSizes[Math.floor(fontSizes.length / 2)] || 12;

    // 6. Group lines into blocks (gap > 1.5 * avgFontSize = new block)
    var blocks = [];
    var blockLines = [lineInfos[0]];
    for (var i = 1; i < lineInfos.length; i++) {
        var prevLine = lineInfos[i - 1];
        var currLine = lineInfos[i];
        var gap = currLine.y - prevLine.y;
        var threshold = medianFontSize * 1.5;

        if (gap > threshold) {
            blocks.push(blockLines);
            blockLines = [currLine];
        } else {
            blockLines.push(currLine);
        }
    }
    blocks.push(blockLines);

    // 7. Classify each block and compute positions
    var result = [];
    var dashRe = /^[\-\u2013\u2014\u2212\u2022\u25CF\u25CB]/;
    var numRe = /^\d+[\.\)]/;

    for (var b = 0; b < blocks.length; b++) {
        var bLines = blocks[b];
        var fullText = bLines.map(function (l) { return l.text; }).join(' ');
        var firstText = bLines[0].text;
        var maxFS = 0;
        for (var k = 0; k < bLines.length; k++) {
            if (bLines[k].fontSize > maxFS) maxFS = bLines[k].fontSize;
        }

        var yTop = bLines[0].y;
        var yBottom = bLines[bLines.length - 1].y + maxFS;

        // Classify
        var type = 'para';
        if (maxFS > medianFontSize * 1.3) {
            type = 'heading';
        } else if (dashRe.test(firstText.trim()) || numRe.test(firstText.trim())) {
            type = 'list';
        } else if (bLines[0].itemCount >= 3) {
            // Heuristic: many separate text fragments on one line could be a table row
            var distinctX = [];
            for (var k = 0; k < bLines[0].xPositions.length; k++) {
                var xp = bLines[0].xPositions[k];
                var isNew = true;
                for (var m = 0; m < distinctX.length; m++) {
                    if (Math.abs(xp - distinctX[m]) < medianFontSize) { isNew = false; break; }
                }
                if (isNew) distinctX.push(xp);
            }
            if (distinctX.length >= 3) {
                type = 'table';
            }
        }

        result.push({
            type: type,
            yTopPct: (yTop / vpHeight) * 100,
            yBottomPct: (yBottom / vpHeight) * 100,
            text: fullText.substring(0, 80)
        });
    }

    return result;
}

/**
 * Build blocks array from server-side PyMuPDF data for a given page.
 * Converts PDF-coordinate bbox into viewport-percentage positions.
 */
function _buildServerBlocks(pageIndex, viewport) {
    if (!window._serverPdfBlocks || !window._serverPdfBlocks[pageIndex]) {
        console.warn('[PDF] No server blocks for page ' + pageIndex + ', using JS fallback');
        return null;
    }
    console.log('[PDF] Using server blocks for page ' + pageIndex + ': ' +
        window._serverPdfBlocks[pageIndex].blocks.length + ' blocks');

    var pageData = window._serverPdfBlocks[pageIndex];
    var scaleX = viewport.width / pageData.width;
    var scaleY = viewport.height / pageData.height;

    // Compute median font size for type classification
    var allFonts = [];
    for (var i = 0; i < pageData.blocks.length; i++) {
        allFonts.push(pageData.blocks[i].max_font_size);
    }
    allFonts.sort(function (a, b) { return a - b; });
    var medianFont = allFonts[Math.floor(allFonts.length / 2)] || 12;

    var dashRe = /^[\-\u2013\u2014\u2212\u2022\u25CF\u25CB]/;
    var numRe = /^\d+[\.\)]/;

    var blocks = [];
    for (var i = 0; i < pageData.blocks.length; i++) {
        var b = pageData.blocks[i];
        var yTopPct = (b.y0 * scaleY / viewport.height) * 100;
        var yBottomPct = (b.y1 * scaleY / viewport.height) * 100;

        // Classify type: use hybrid pre-classified type if available,
        // otherwise fall back to font-size heuristics
        var type = 'para';
        if (b._hybrid_type) {
            type = b._hybrid_type;
        } else if (b.max_font_size > medianFont * 1.3) {
            type = 'heading';
        } else if (dashRe.test(b.text.trim()) || numRe.test(b.text.trim())) {
            type = 'list';
        }

        blocks.push({
            type: type,
            yTopPct: yTopPct,
            yBottomPct: yBottomPct,
            text: b.text || '',
            elementId: b._hybrid_element_id || null
        });
    }
    return blocks;
}

/**
 * Create an overlay div on a PDF page wrapper with annotation markers.
 * Returns the number of blocks (annotations) created.
 * pageIndex is 0-based page index for server block lookup.
 */
function createPdfOverlayFn(wrapper, textContent, viewport, startIdx, pageIndex) {
    // Try server-side blocks first (PyMuPDF), fallback to JS heuristics
    var blocks = _buildServerBlocks(pageIndex, viewport);
    if (!blocks) {
        blocks = analyzePdfTextContent(textContent, viewport);
    }
    if (blocks.length === 0) return 0;

    var overlay = document.createElement('div');
    overlay.className = 'pdf-overlay';

    for (var i = 0; i < blocks.length; i++) {
        var block = blocks[i];
        var idx = startIdx + i + 1; // 1-based
        var type = normType(block.type);
        var label = ANNO_TYPE_LABELS[type] || type;
        var color = getAnnoColor(idx);

        var marker = document.createElement('div');
        marker.className = 'anno-marker';
        marker.style.top = block.yTopPct + '%';
        marker.style.height = Math.max(block.yBottomPct - block.yTopPct, 1.5) + '%';
        marker.style.setProperty('--anno-clr', color);
        marker.setAttribute('data-anno-idx', String(idx));
        marker.setAttribute('data-anno-type', type);
        marker.setAttribute('data-anno-top', String(block.yTopPct));
        marker.setAttribute('data-anno-bottom', String(block.yBottomPct));
        marker.setAttribute('data-anno-text', block.text || '');
        if (block.elementId) {
            marker.setAttribute('data-element-id', block.elementId);
        }

        var labelSpan = document.createElement('span');
        labelSpan.className = 'marker-label';
        labelSpan.textContent = label + ' ' + idx;
        marker.appendChild(labelSpan);

        marker.addEventListener('click', makeNavHandler(idx));

        overlay.appendChild(marker);
    }

    wrapper.appendChild(overlay);
    return blocks.length;
}

/**
 * Public API for the PDF rendering module script.
 * Creates overlay, recalculates indices, and syncs markers if reference loaded.
 */
export function createPdfOverlay(wrapper, textContent, viewport, startIdx, pageIndex) {
    var count = createPdfOverlayFn(wrapper, textContent, viewport, startIdx, pageIndex);
    // Recalculate max indices after new PDF page annotations added
    recalcMaxIdx();
    updatePosition();

    // If reference is loaded, sync ALL markers globally (position-based mapping
    // requires global view across all pages)
    var refData = state.getReferenceData();
    if (refData && refData.elements) {
        var allMarkers = dom.docxPanel.querySelectorAll('.anno-marker');
        if (allMarkers.length > 0) {
            syncPdfMarkers(allMarkers);
        }
    }

    return count;
}
