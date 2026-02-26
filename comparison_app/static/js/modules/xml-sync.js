/**
 * xml-sync.js — Synchronize annotation indices onto S1000D (right) panel elements.
 *
 * Uses 3-phase matching (stable_id -> text similarity -> type-group fallback)
 * to align reference element indices with rendered XML DOM elements,
 * handling XSD reordering where warnings/cautions float above paragraphs.
 */

import { NESTED_LIST_TYPES } from './config.js';
import { getReferenceData, dom } from './state.js';
import { normType, filterTopLevel } from './utils.js';
import { getAnnoColor } from './badges.js';

/**
 * Sync right (S1000D) panel indices to match reference data.
 * Uses 3-phase matching:
 *   Phase 1: stable_id (data-element-id attribute)
 *   Phase 2: text prefix similarity
 *   Phase 3: type-group counter fallback
 * Followed by a nested list pass for nested list elements within parent lists.
 * Does NOT overwrite data-anno-type -- the renderer's type is correct.
 */
export function syncS1000dElements() {
    var referenceData = getReferenceData();
    var s1000dPanel = dom.s1000dPanel;

    if (!referenceData || !referenceData.elements) return;

    var annoEls = s1000dPanel.querySelectorAll('[data-anno-idx], [data-anno-type]');
    var filtered = filterTopLevel(annoEls, s1000dPanel);

    // Build lookup from stable_id -> ref element for ID-based matching
    var refByStableId = {};
    for (var j = 0; j < referenceData.elements.length; j++) {
        var refElem = referenceData.elements[j];
        if (refElem.type === '_skip') continue;
        if (NESTED_LIST_TYPES[refElem.type]) continue;
        var sid = refElem.stable_id || '';
        if (sid && !refByStableId[sid]) {
            refByStableId[sid] = refElem;
        }
    }

    // Build per-type idx queues for fallback matching
    var refByType = {};
    for (var j = 0; j < referenceData.elements.length; j++) {
        var refElem = referenceData.elements[j];
        if (refElem.type === '_skip') continue;
        if (NESTED_LIST_TYPES[refElem.type]) continue;
        var nt = normType(refElem.type);
        if (!refByType[nt]) refByType[nt] = [];
        refByType[nt].push(refElem.idx);
    }

    // Phase 1: Match by stable_id (data-element-id attribute)
    var usedRefIdx = {};
    var matchedEls = new Set();
    for (var i = 0; i < filtered.length; i++) {
        var el = filtered[i];
        var eid = el.getAttribute('data-element-id') || '';
        if (eid && refByStableId[eid] && !usedRefIdx[refByStableId[eid].idx]) {
            var matched = refByStableId[eid];
            el.setAttribute('data-anno-idx', String(matched.idx));
            el.style.setProperty('--anno-clr', getAnnoColor(matched.idx));
            usedRefIdx[matched.idx] = true;
            matchedEls.add(i);
        }
    }

    // Phase 2: Text-based matching for unmatched elements.
    // Compare DOM element innerText prefix against ref text_start.
    // This is more robust than type-group counters when element counts
    // differ between reference and XML.
    var refUnused = [];
    for (var j = 0; j < referenceData.elements.length; j++) {
        var refElem = referenceData.elements[j];
        if (refElem.type === '_skip') continue;
        if (NESTED_LIST_TYPES[refElem.type]) continue;
        if (usedRefIdx[refElem.idx]) continue;
        refUnused.push(refElem);
    }

    for (var i = 0; i < filtered.length; i++) {
        if (matchedEls.has(i)) continue;
        var el = filtered[i];
        var elText = (el.innerText || el.textContent || '').trim().toLowerCase();
        if (!elText) continue;
        var elPrefix = elText.substring(0, 60);

        var bestRef = null;
        var bestScore = 0;
        for (var r = 0; r < refUnused.length; r++) {
            var cand = refUnused[r];
            if (usedRefIdx[cand.idx]) continue;
            var refText = (cand.text_start || '').trim().toLowerCase();
            if (!refText) continue;

            // Prefix match: count matching chars from start
            var cmpLen = Math.min(elPrefix.length, refText.length, 50);
            var matchChars = 0;
            for (var k = 0; k < cmpLen; k++) {
                if (elPrefix.charCodeAt(k) === refText.charCodeAt(k)) matchChars++;
                else break;
            }
            var score = cmpLen > 0 ? matchChars / cmpLen : 0;
            // Bonus for type match
            var nt = normType(el.getAttribute('data-anno-type') || 'para');
            if (nt === normType(cand.type)) score += 0.05;

            if (score > bestScore && score > 0.5) {
                bestScore = score;
                bestRef = cand;
            }
        }

        if (bestRef) {
            el.setAttribute('data-anno-idx', String(bestRef.idx));
            el.style.setProperty('--anno-clr', getAnnoColor(bestRef.idx));
            usedRefIdx[bestRef.idx] = true;
            matchedEls.add(i);
        }
    }

    // Phase 3: Fallback -- type-group matching for still-unmatched elements
    var typeCounters = {};
    for (var i = 0; i < filtered.length; i++) {
        if (matchedEls.has(i)) {
            var el = filtered[i];
            var rendererType = el.getAttribute('data-anno-type') || 'para';
            var nt = normType(rendererType);
            typeCounters[nt] = (typeCounters[nt] || 0) + 1;
        }
    }
    var typeCountersFallback = {};
    for (var nt2 in typeCounters) {
        typeCountersFallback[nt2] = typeCounters[nt2];
    }
    for (var i = 0; i < filtered.length; i++) {
        if (matchedEls.has(i)) continue;
        var el = filtered[i];
        var rendererType = el.getAttribute('data-anno-type') || 'para';
        var nt = normType(rendererType);
        typeCountersFallback[nt] = typeCountersFallback[nt] || 0;

        var queue = refByType[nt];
        if (queue && typeCountersFallback[nt] < queue.length) {
            var refIdx = queue[typeCountersFallback[nt]];
            if (!usedRefIdx[refIdx]) {
                el.setAttribute('data-anno-idx', String(refIdx));
                el.style.setProperty('--anno-clr', getAnnoColor(refIdx));
                usedRefIdx[refIdx] = true;
            }
        }
        typeCountersFallback[nt]++;
    }

    // Nested list pass: annotate nested list DOM elements within parent lists.
    var lastListIdx = null;
    for (var j = 0; j < referenceData.elements.length; j++) {
        var refElem = referenceData.elements[j];
        if (refElem.type === '_skip') continue;

        if (NESTED_LIST_TYPES[refElem.type]) {
            if (lastListIdx === null) continue;
            var parentEl = s1000dPanel.querySelector('[data-anno-idx="' + lastListIdx + '"]');
            if (!parentEl) continue;

            var nestedLists = parentEl.querySelectorAll(
                'ul:not([data-anno-idx]), ol:not([data-anno-idx])'
            );
            if (nestedLists.length > 0) {
                var nestedEl = nestedLists[0];
                nestedEl.setAttribute('data-anno-idx', String(refElem.idx));
                nestedEl.setAttribute('data-anno-type', refElem.type);
                nestedEl.style.setProperty('--anno-clr', getAnnoColor(refElem.idx));
            }
        } else {
            var baseType = normType(refElem.type);
            if (baseType === 'unnumbered_list' || baseType === 'numbered_list') {
                lastListIdx = refElem.idx;
            }
        }
    }
}
