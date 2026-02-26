/**
 * pdf-sync.js — Synchronization between PDF markers and reference elements.
 *
 * Routes to bbox-based (for XML-derived refs) or sequential (for old refs)
 * marker mapping.  Extracted from comparison.js lines 360-667.
 */

import { ANNO_TYPE_LABELS } from './config.js';
import { getReferenceData, dom } from './state.js';
import { normType, normForMatch, getMarkerOverlay, getMarkerPage } from './utils.js';
import { log, logInfo, logGroup, logGroupEnd, logTime } from './logger.js';
import { getAnnoColor } from './badges.js';

// ── Exported helpers ─────────────────────────────────────────────────

/**
 * True when the loaded reference was created by the XML-first algorithm.
 * Accesses referenceData via getReferenceData().
 */
export function isXmlDerivedRef() {
    var referenceData = getReferenceData();
    if (!referenceData || !referenceData.elements) return false;
    if (referenceData.source === 'auto_xml_derived') return true;
    return referenceData.elements.some(function (e) { return e.type_source === 'xml_derived'; });
}

/**
 * Render bracket-markers for all .anno-marker elements on the PDF panel.
 * For XML-derived references: uses bbox-based positional matching so that
 * warnings/notes on page 10 don't get mapped to page-1 markers.
 * For old references: keeps the original sequential span-based mapping.
 */
export function syncPdfMarkers(markers) {
    // Convert NodeList to array (DOM order is page-by-page top-to-bottom)
    var sorted = [];
    for (var i = 0; i < markers.length; i++) sorted.push(markers[i]);

    if (isXmlDerivedRef()) {
        _syncPdfMarkersBbox(sorted);
    } else {
        _syncPdfMarkersSequential(sorted);
    }
}

/** Render label + bracket styling for a list of page groups (shared by both sync modes) */
export function renderMarkerBrackets(pageGroups, label) {
    for (var g = 0; g < pageGroups.length; g++) {
        var group = pageGroups[g];
        var isLast = (g === pageGroups.length - 1);
        for (var m = 0; m < group.markers.length; m++) {
            var mk = group.markers[m];
            if (m === 0) {
                mk.style.display = '';
                var labelEl = mk.querySelector('.marker-label');
                var displayLabel = (g === 0) ? label : '\u21A7 ' + label;
                if (labelEl) labelEl.textContent = displayLabel;
                else mk.textContent = displayLabel;
                var top = group.firstTop;
                var bottom = isLast ? group.lastBottom : 100;
                mk.style.top = top + '%';
                mk.style.height = Math.max(bottom - top, 1.5) + '%';
            } else {
                mk.style.display = 'none';
            }
        }
    }
}

/** Style a single marker as "unassigned" (green dashed, available for Create) */
export function markUnassigned(um) {
    um.style.display = '';
    um.removeAttribute('data-anno-idx');
    um.classList.add('anno-marker-unassigned');
    um.style.setProperty('--anno-clr', '#27ae60');
    um.style.opacity = '0.6';
    um.style.borderStyle = 'dashed';
    var uLabel = um.querySelector('.marker-label');
    if (uLabel) uLabel.textContent = '+';
}

// ── Internal functions ───────────────────────────────────────────────

/** Original sequential span-based mapping (for non-XML-derived references) */
function _syncPdfMarkersSequential(sorted) {
    var referenceData = getReferenceData();
    var refLen = referenceData.elements.length;
    var markerIdx = 0;
    var pdfTypeCounts = {};

    for (var r = 0; r < refLen && markerIdx < sorted.length; r++) {
        var refElem = referenceData.elements[r];
        var span = refElem.span || 1;
        var type = refElem.type;

        if (type === '_skip') {
            for (var s = 0; s < span && markerIdx < sorted.length; s++) {
                sorted[markerIdx].style.display = 'none';
                sorted[markerIdx].removeAttribute('data-anno-idx');
                markerIdx++;
            }
            continue;
        }

        var idx = refElem.idx;
        var normT = normType(type);
        pdfTypeCounts[normT] = (pdfTypeCounts[normT] || 0) + 1;
        var typeNum = pdfTypeCounts[normT];
        var label = (ANNO_TYPE_LABELS[normT] || normT) + typeNum + ' [' + idx + ']';
        var color = getAnnoColor(idx);
        var pageGroups = [];
        var curGroup = null;
        var source = refElem.type_source || 'auto';

        for (var s2 = 0; s2 < span && markerIdx < sorted.length; s2++) {
            var marker = sorted[markerIdx];
            marker.setAttribute('data-anno-idx', String(idx));
            marker.setAttribute('data-anno-type', type);
            marker.setAttribute('data-anno-source', source);
            marker.style.setProperty('--anno-clr', color);
            marker.style.opacity = '';
            marker.style.borderStyle = '';
            marker.classList.remove('anno-marker-unassigned');

            var overlay = getMarkerOverlay(marker);
            if (!curGroup || overlay !== curGroup.overlay) {
                curGroup = {
                    overlay: overlay,
                    markers: [],
                    firstTop: parseFloat(marker.getAttribute('data-anno-top')),
                    lastBottom: parseFloat(marker.getAttribute('data-anno-bottom'))
                };
                pageGroups.push(curGroup);
            }
            curGroup.markers.push(marker);
            var mBottom = parseFloat(marker.getAttribute('data-anno-bottom'));
            if (mBottom > curGroup.lastBottom) curGroup.lastBottom = mBottom;
            markerIdx++;
        }

        renderMarkerBrackets(pageGroups, label);
    }

    for (; markerIdx < sorted.length; markerIdx++) {
        markUnassigned(sorted[markerIdx]);
    }
}

/**
 * Text+position-based marker mapping for XML-derived references.
 * Uses text prefix matching to find the best marker for each reference
 * element, with bbox.page as a page hint.  Falls back to position-based
 * matching when text is unavailable.  Works correctly even when markers
 * come from a different algorithm (match_pdf_to_docx) than the reference
 * (match_xml_to_pdf), because text content is the common denominator.
 */
function _syncPdfMarkersBbox(sorted) {
    var endTimer = logTime('pdf-sync', 'syncPdfMarkersBbox');

    var referenceData = getReferenceData();

    // Build flat info list with per-marker normalized text
    var allInfos = [];
    var byPage = {};

    for (var i = 0; i < sorted.length; i++) {
        var mk = sorted[i];
        var pg = getMarkerPage(mk, dom.docxPanel);
        var top = parseFloat(mk.getAttribute('data-anno-top') || '0');
        var bot = parseFloat(mk.getAttribute('data-anno-bottom') || '0');
        var rawText = mk.getAttribute('data-anno-text') || '';
        var info = {
            marker: mk, page: pg, top: top, bot: bot,
            normText: normForMatch(rawText),
            used: false, globalIdx: i
        };
        if (!byPage[pg]) byPage[pg] = [];
        byPage[pg].push(info);
        allInfos.push(info);
    }

    var pdfTypeCounts = {};
    var refElems = referenceData.elements;

    logGroup('pdf-sync', 'syncPdfMarkersBbox: ' + refElems.length + ' elements, ' + sorted.length + ' markers');

    for (var r = 0; r < refElems.length; r++) {
        var refElem = refElems[r];
        var type = refElem.type;

        if (type === '_skip') continue;
        if (type === '_unmatched_xml') continue;
        if (type === '_extra_pdf') continue;

        var refNorm = normForMatch(refElem.text_start || '');
        var bbox = refElem.bbox;

        // Determine which markers to search: prefer same page if bbox exists
        var candidates;
        if (bbox && bbox.page) {
            candidates = (byPage[bbox.page] || []).slice();
            // Also include adjacent pages in case of cross-page elements
            var prev = byPage[bbox.page - 1] || [];
            var next = byPage[bbox.page + 1] || [];
            candidates = candidates.concat(prev, next);
        } else {
            // No bbox (e.g. newly created element) -> search all markers
            candidates = allInfos;
        }

        // Find best matching unused marker by text prefix
        var bestInfo = null;
        var bestScore = -1;

        if (refNorm.length > 0) {
            for (var mi = 0; mi < candidates.length; mi++) {
                if (candidates[mi].used) continue;
                var cNorm = candidates[mi].normText;
                if (!cNorm) continue;
                // Prefix overlap score
                var mLen = Math.min(refNorm.length, cNorm.length);
                if (mLen === 0) continue;
                var common = 0;
                for (var ci = 0; ci < mLen; ci++) {
                    if (refNorm[ci] === cNorm[ci]) common++; else break;
                }
                var score = common / Math.max(refNorm.length, 1);
                if (score > bestScore) {
                    bestScore = score; bestInfo = candidates[mi];
                } else if (score === bestScore && score > 0.5 && bbox && bbox.page) {
                    // Tie-break: prefer marker on the same page as bbox
                    if (candidates[mi].page === bbox.page &&
                        (!bestInfo || bestInfo.page !== bbox.page)) {
                        bestInfo = candidates[mi];
                    }
                }
            }
        }

        // Fallback: position-based matching if text match is poor
        if ((!bestInfo || bestScore < 0.3) && bbox && bbox.page) {
            var pageData = window._serverPdfBlocks
                ? window._serverPdfBlocks[bbox.page - 1] : null;
            var pageHeight = pageData ? pageData.height : 792;
            var yTarget = (bbox.y0 / pageHeight) * 100;
            var pageMarkers = byPage[bbox.page] || [];
            var posBest = null;
            var posDist = Infinity;
            for (var pi = 0; pi < pageMarkers.length; pi++) {
                if (pageMarkers[pi].used) continue;
                var dist = Math.abs(pageMarkers[pi].top - yTarget);
                if (dist < posDist) { posDist = dist; posBest = pageMarkers[pi]; }
            }
            if (posBest && posDist < 5) bestInfo = posBest;
        }

        if (!bestInfo) {
            log('pdf-sync', 'elem[' + r + '] type=' + type + ' text="' + refNorm.substring(0, 30) + '" → NO MATCH');
            continue;
        }

        log('pdf-sync', 'elem[' + r + '] type=' + type + ' → marker page=' + bestInfo.page + ' score=' + bestScore.toFixed(2));

        bestInfo.used = true;
        var span = refElem.span || 1;
        var idx = refElem.idx;
        var normT = normType(type);
        pdfTypeCounts[normT] = (pdfTypeCounts[normT] || 0) + 1;
        var typeNum = pdfTypeCounts[normT];
        var label = (ANNO_TYPE_LABELS[normT] || normT) + typeNum + ' [' + idx + ']';
        var color = getAnnoColor(idx);
        var source = refElem.type_source || 'auto';

        // Claim anchor marker
        var anchorMarker = bestInfo.marker;
        anchorMarker.setAttribute('data-anno-idx', String(idx));
        anchorMarker.setAttribute('data-anno-type', type);
        anchorMarker.setAttribute('data-anno-source', source);
        anchorMarker.style.setProperty('--anno-clr', color);
        anchorMarker.style.opacity = '';
        anchorMarker.style.borderStyle = '';
        anchorMarker.classList.remove('anno-marker-unassigned');

        var pageGroups = [];
        var curGroup = {
            overlay: getMarkerOverlay(anchorMarker),
            markers: [anchorMarker],
            firstTop: bestInfo.top,
            lastBottom: bestInfo.bot
        };
        pageGroups.push(curGroup);

        // Claim span-1 more consecutive unused markers in document order
        var claimed = 1;
        for (var si = bestInfo.globalIdx + 1;
             si < allInfos.length && claimed < span; si++) {
            var mInfo = allInfos[si];
            if (mInfo.used) continue;
            mInfo.used = true;

            var marker = mInfo.marker;
            marker.setAttribute('data-anno-idx', String(idx));
            marker.setAttribute('data-anno-type', type);
            marker.setAttribute('data-anno-source', source);
            marker.style.setProperty('--anno-clr', color);
            marker.style.opacity = '';
            marker.style.borderStyle = '';
            marker.classList.remove('anno-marker-unassigned');

            var ov = getMarkerOverlay(marker);
            if (ov !== curGroup.overlay) {
                curGroup = {
                    overlay: ov, markers: [],
                    firstTop: mInfo.top, lastBottom: mInfo.bot
                };
                pageGroups.push(curGroup);
            }
            curGroup.markers.push(marker);
            if (mInfo.bot > curGroup.lastBottom) curGroup.lastBottom = mInfo.bot;
            claimed++;
        }

        renderMarkerBrackets(pageGroups, label);
    }

    // Remaining unused markers -> unassigned (available for Create)
    var claimedCount = 0;
    var unassigned = 0;
    for (var ui = 0; ui < allInfos.length; ui++) {
        if (allInfos[ui].used) {
            claimedCount++;
        } else {
            markUnassigned(allInfos[ui].marker);
            unassigned++;
        }
    }

    logInfo('pdf-sync', 'Result: ' + claimedCount + ' claimed, ' + unassigned + ' unassigned');
    logGroupEnd('pdf-sync');
    endTimer();
}
