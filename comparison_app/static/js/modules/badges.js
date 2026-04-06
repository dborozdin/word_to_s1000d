/**
 * badges.js — Badge injection, lifecycle, and position display.
 *
 * Handles creating .anno-badge spans on annotated elements,
 * rebuilding badges after edits, and maintaining the "X / Y"
 * position indicator in the toolbar.
 */

import { ANNO_TYPE_LABELS, ANNO_COLORS } from './config.js';
import { dom, getReferenceData, getCurrentIdx, getMaxIdx as stateGetMaxIdx, setMaxIdx } from './state.js';
import { normType } from './utils.js';

// ── Hook registry ────────────────────────────────────────────────────
// Other modules (pdf-sync, html-sync, mismatch, navigation) set these
// during their initialization so that rebuildBadges / injectBadges can
// call back without creating circular imports.
/**
 * Hook functions set by other modules during initialization.
 * - syncPdfMarkers(markers)  — set by pdf-sync module
 * - syncHtmlElements(allBlocks, panel) — set by html-sync module
 * - detectMismatch()         — set by mismatch module
 * - makeNavHandler(idx)      — set by navigation module, returns click handler
 */
export const _rebuildHooks = {
    syncPdfMarkers: null,
    syncHtmlElements: null,
    detectMismatch: null,
    makeNavHandler: null
};

// ── Public API ───────────────────────────────────────────────────────

/**
 * Return a color from the ANNO_COLORS palette for the given 1-based index.
 * Wraps around when idx exceeds the palette length.
 *
 * @param {number} idx — 1-based annotation index
 * @returns {string} CSS color string (hex)
 */
export function getAnnoColor(idx) {
    return ANNO_COLORS[(idx - 1) % ANNO_COLORS.length];
}

/**
 * Return the highest `data-anno-idx` value found in visible, assigned
 * elements within the given panel.
 *
 * Hidden elements (`display:none`) and unassigned markers
 * (`.anno-marker-unassigned`) are excluded from the count.
 *
 * @param {HTMLElement} panel — the DOM container to scan
 * @returns {number} highest index, or 0 if none found
 */
export function getMaxIdx(panel) {
    var elements = panel.querySelectorAll('[data-anno-idx]');
    var max = 0;
    for (var i = 0; i < elements.length; i++) {
        if (elements[i].style.display === 'none') continue;
        if (elements[i].classList.contains('anno-marker-unassigned')) continue;
        var idx = parseInt(elements[i].getAttribute('data-anno-idx'), 10);
        if (idx > max) max = idx;
    }
    return max;
}

/**
 * Recalculate maxLeftIdx / maxRightIdx / maxIdx from the current DOM
 * and push the values into the centralized state via `setMaxIdx`.
 */
export function recalcMaxIdx() {
    var maxLeftIdx = getMaxIdx(dom.docxPanel);
    var maxRightIdx = getMaxIdx(dom.s1000dPanel);
    setMaxIdx(maxLeftIdx, maxRightIdx);
}

/**
 * Create `.anno-badge` start/end spans for every annotated element
 * (`[data-anno-idx]`) inside the given panel.
 *
 * Skips:
 * - `.anno-marker` elements (PDF overlay markers — badges not applicable)
 * - Elements with `data-anno-cont` (continuation fragments)
 * - Elements that already have a badge injected
 *
 * Each badge shows a composite label like "пар.3 [5]" (type-counter + global idx)
 * and receives a click handler via the `_rebuildHooks.makeNavHandler` hook.
 *
 * @param {HTMLElement} panel — the DOM container to process
 */
export function injectBadges(panel) {
    var elements = panel.querySelectorAll('[data-anno-idx]');
    // Collect badge-eligible elements and sort by idx for per-type counting
    var eligible = [];
    for (var i = 0; i < elements.length; i++) {
        var el = elements[i];
        if (el.classList.contains('anno-marker')) continue;
        if (el.hasAttribute('data-anno-cont')) continue;
        if (el.querySelector('.anno-badge')) continue;
        eligible.push(el);
    }
    eligible.sort(function(a, b) {
        return parseInt(a.getAttribute('data-anno-idx'), 10) -
               parseInt(b.getAttribute('data-anno-idx'), 10);
    });

    var typeCounts = {};
    for (var i = 0; i < eligible.length; i++) {
        var el = eligible[i];
        var idx = parseInt(el.getAttribute('data-anno-idx'), 10);
        var type = normType(el.getAttribute('data-anno-type') || 'para');
        typeCounts[type] = (typeCounts[type] || 0) + 1;
        var typeNum = typeCounts[type];
        var typeLabel = ANNO_TYPE_LABELS[type] || type;
        var label = typeLabel + typeNum + ' [' + idx + ']';
        var color = getAnnoColor(idx);

        // Ensure element has relative positioning for badge
        var pos = window.getComputedStyle(el).position;
        if (pos === 'static') {
            el.style.position = 'relative';
        }

        // Start badge
        var badge = document.createElement('span');
        badge.className = 'anno-badge anno-badge-start';
        badge.textContent = label;
        badge.style.setProperty('--anno-clr', color);
        badge.setAttribute('data-badge-idx', String(idx));
        var annoSource = el.getAttribute('data-anno-source');
        if (annoSource) badge.setAttribute('data-anno-source', annoSource);
        el.insertBefore(badge, el.firstChild);

        // End marker
        var endMarker = document.createElement('span');
        endMarker.className = 'anno-badge anno-badge-end';
        endMarker.textContent = '/' + idx;
        endMarker.style.setProperty('--anno-clr', color);
        endMarker.setAttribute('data-badge-idx', String(idx));
        el.appendChild(endMarker);

        // Left border color
        el.style.setProperty('--anno-clr', color);

        // Click handlers — delegate to navigation module via hook
        if (_rebuildHooks.makeNavHandler) {
            badge.addEventListener('click', _rebuildHooks.makeNavHandler(idx));
            endMarker.addEventListener('click', _rebuildHooks.makeNavHandler(idx));
        }
    }
}

/**
 * Full badge rebuild cycle for a single panel:
 *
 * 1. Remove all existing `.anno-badge` elements from the panel.
 * 2. If the panel is the left (docx) panel and referenceData is loaded,
 *    re-sync DOM elements with the reference — delegates to the
 *    `syncPdfMarkers` or `syncHtmlElements` hook depending on render mode.
 * 3. Re-inject fresh badges via `injectBadges`.
 * 4. Recalculate navigation counters and re-run mismatch detection.
 *
 * @param {HTMLElement} panel — the DOM container to rebuild
 */
export function rebuildBadges(panel) {
    // 1. Remove all existing badges from the panel
    var oldBadges = panel.querySelectorAll('.anno-badge');
    for (var i = oldBadges.length - 1; i >= 0; i--) {
        oldBadges[i].parentNode.removeChild(oldBadges[i]);
    }

    // 2. Sync DOM elements with referenceData (if in edit mode)
    var referenceData = getReferenceData();
    if (referenceData && referenceData.elements && panel === dom.docxPanel) {
        // Collect all annotated elements, separated by type
        var pdfMarkers = panel.querySelectorAll('.anno-marker');
        var allAnno = panel.querySelectorAll('[data-anno-idx]');

        if (pdfMarkers.length > 0) {
            // PDF mode: check if markers are pre-synced (procedural xml_matched)
            var hasPreSynced = false;
            for (var mi = 0; mi < pdfMarkers.length; mi++) {
                if (pdfMarkers[mi].getAttribute('data-anno-source') === 'xml_derived') {
                    hasPreSynced = true;
                    break;
                }
            }
            if (!hasPreSynced && _rebuildHooks.syncPdfMarkers) {
                _rebuildHooks.syncPdfMarkers(pdfMarkers);
            }
        } else {
            // HTML mode: sync block elements by position
            // Include cleared blocks in the query so they can be re-assigned
            var allBlocks = panel.querySelectorAll('[data-anno-idx], [data-anno-idx-cleared]');
            if (_rebuildHooks.syncHtmlElements) {
                _rebuildHooks.syncHtmlElements(allBlocks, panel);
            }
        }
    }

    // 3. Re-inject badges (only for HTML block elements, skips .anno-marker)
    injectBadges(panel);

    // 4. Recalculate navigation and mismatch
    recalcMaxIdx();
    updatePosition();
    if (_rebuildHooks.detectMismatch) {
        _rebuildHooks.detectMismatch();
    }
}

/**
 * Update the position indicator span with "currentIdx / maxIdx".
 * Displays "— / maxIdx" when no element is selected (currentIdx === 0).
 */
export function updatePosition() {
    if (!dom.positionSpan) return;
    var currentIdx = getCurrentIdx();
    var maxIdx = stateGetMaxIdx();
    if (currentIdx > 0) {
        dom.positionSpan.textContent = currentIdx + ' / ' + maxIdx;
    } else {
        dom.positionSpan.textContent = '\u2014 / ' + maxIdx;
    }
}
