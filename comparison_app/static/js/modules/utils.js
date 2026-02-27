/**
 * utils.js — Shared utility functions for the comparison module.
 *
 * Pure functions with no side effects and no state dependencies.
 */

/**
 * Normalize type aliases: "paragraph"↔"para", "illustration"↔"figure".
 * Used for composite numbering and sync.
 */
export function normType(t) {
    if (t === 'paragraph' || t === 'para') return 'para';
    if (t === 'illustration' || t === 'figure') return 'figure';
    return t;
}

/**
 * Coarser normalization for order comparison.
 * Collapses list variants since S1000D uses <randomList> for all.
 */
export function normTypeForOrder(t) {
    var nt = normType(t);
    if (nt === 'numbered_list' || nt === 'unnumbered_list') return 'list';
    if (nt === 'nested_numbered_list' || nt === 'nested_unnumbered_list') return 'nested_list';
    return nt;
}

/**
 * Normalize text for prefix-match comparison (mirrors Python _normalize_for_match).
 * Strips leading bullets/numbers, lowercases, collapses whitespace, takes first 80 chars.
 */
export function normForMatch(text) {
    return (text || '').toLowerCase()
        .replace(/^[\-\u2013\u2014\u2022]+\s*/, '')   // bullets: –, —, •
        .replace(/^\d+[\.\)]\s+/, '')                   // "1. " / "1) "
        .replace(/^\d+(?:\.\d+)*\s+/, '')               // "3.1.2 "
        .replace(/\s+/g, ' ').trim()
        .slice(0, 80);
}

/**
 * Light normalization: only lowercase + collapse whitespace, NO number stripping.
 * Preserves multi-level numbers like "3.1.1", "3.1.2" so items with different
 * numbering but identical body text can still be distinguished.
 */
export function normForMatchLight(text) {
    return (text || '').toLowerCase()
        .replace(/\s+/g, ' ').trim()
        .slice(0, 80);
}

/**
 * Compute prefix-overlap score between two normalized strings.
 * Returns a value in [0, 1] — the fraction of `a` matched as a prefix of `b`.
 */
export function prefixScore(a, b) {
    if (!a || !b) return 0;
    var len = Math.min(a.length, b.length);
    var common = 0;
    for (var i = 0; i < len; i++) {
        if (a[i] === b[i]) common++; else break;
    }
    return common / Math.max(a.length, 1);
}

/**
 * Get clean text from a DOM element (strips .anno-badge children).
 * Returns first 80 chars, trimmed.
 */
export function getCleanText(el) {
    var clone = el.cloneNode(true);
    var badges = clone.querySelectorAll('.anno-badge');
    for (var i = badges.length - 1; i >= 0; i--) badges[i].parentNode.removeChild(badges[i]);
    return (clone.textContent || '').trim().substring(0, 80);
}

/**
 * Filter a NodeList to top-level annotated elements only (skip nested).
 * An element is "nested" if any ancestor (up to `panel`) has data-anno-idx.
 */
export function filterTopLevel(nodeList, panel) {
    var result = [];
    for (var k = 0; k < nodeList.length; k++) {
        var parent = nodeList[k].parentElement;
        var nested = false;
        while (parent && parent !== panel) {
            if (parent.hasAttribute &&
                (parent.hasAttribute('data-anno-idx') || parent.hasAttribute('data-anno-idx-cleared'))) {
                nested = true;
                break;
            }
            parent = parent.parentElement;
        }
        if (!nested) result.push(nodeList[k]);
    }
    return result;
}

/**
 * Get the .pdf-overlay parent of a marker element.
 */
export function getMarkerOverlay(marker) {
    return marker.parentNode;
}

/**
 * Determine 1-based page number of an .anno-marker by its DOM position
 * within .pdf-page-wrapper elements.
 */
export function getMarkerPage(marker, docxPanel) {
    var overlay = getMarkerOverlay(marker);
    if (!overlay) return 1;
    var wrapper = overlay.parentElement;
    var allWrappers = docxPanel.querySelectorAll('.pdf-page-wrapper');
    for (var _wi = 0; _wi < allWrappers.length; _wi++) {
        if (allWrappers[_wi] === wrapper) return _wi + 1;
    }
    return 1;
}

/**
 * Convert marker's percentage top → absolute PDF y-coordinate.
 * Uses window._serverPdfBlocks for page dimensions.
 */
export function markerTopToAbsolute(marker, docxPanel) {
    var page = getMarkerPage(marker, docxPanel);
    var topPct = parseFloat(marker.getAttribute('data-anno-top') || '0');
    var pageData = window._serverPdfBlocks
        ? window._serverPdfBlocks[page - 1] : null;
    var pageHeight = pageData ? pageData.height : 792;
    return (topPct / 100) * pageHeight;
}
