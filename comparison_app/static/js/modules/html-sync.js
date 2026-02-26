/**
 * html-sync.js — Synchronize annotation data onto DOCX (left) panel HTML elements.
 *
 * Routes to text-based or sequential mapping depending on whether the
 * loaded reference was created by the XML-first algorithm.
 */

import { getReferenceData } from './state.js';
import { normForMatch, getCleanText, filterTopLevel } from './utils.js';
import { getAnnoColor } from './badges.js';
import { isXmlDerivedRef } from './pdf-sync.js';

/**
 * Annotate HTML block elements on the DOCX panel.
 * For XML-derived references: uses text prefix-matching so that elements
 * are placed at the correct DOM block regardless of XML semantic order.
 * For old references: keeps the original sequential span-based mapping.
 *
 * @param {NodeList|Array} allAnno - All annotated/annotatable elements in the panel
 * @param {HTMLElement} panel - The DOCX panel container element
 */
export function syncHtmlElements(allAnno, panel) {
    var annoEls = filterTopLevel(allAnno, panel);

    if (isXmlDerivedRef()) {
        _syncHtmlElementsText(annoEls);
    } else {
        _syncHtmlElementsSequential(annoEls);
    }
}

/**
 * Clear annotation attributes from a DOM element (mark as available for Create).
 *
 * @param {HTMLElement} el - The DOM element to clear
 */
export function clearAnnoEl(el) {
    el.removeAttribute('data-anno-idx');
    el.removeAttribute('data-anno-type');
    el.removeAttribute('data-anno-cont');
    el.removeAttribute('data-anno-source');
    el.style.removeProperty('--anno-clr');
    el.style.borderLeft = '';
    el.setAttribute('data-anno-idx-cleared', '1');
}

/** Original sequential span-based mapping (for non-XML-derived references) */
function _syncHtmlElementsSequential(annoEls) {
    var referenceData = getReferenceData();
    var refLen = referenceData.elements.length;
    var domIdx = 0;

    for (var j = 0; j < refLen; j++) {
        var refElem = referenceData.elements[j];
        var span = refElem.span || 1;

        if (refElem.type === '_skip') {
            for (var s = 0; s < span && domIdx < annoEls.length; s++) {
                clearAnnoEl(annoEls[domIdx]);
                domIdx++;
            }
            continue;
        }

        var color = getAnnoColor(refElem.idx);
        var source = refElem.type_source || 'auto';

        for (var s2 = 0; s2 < span && domIdx < annoEls.length; s2++) {
            annoEls[domIdx].setAttribute('data-anno-idx', String(refElem.idx));
            annoEls[domIdx].setAttribute('data-anno-type', refElem.type);
            annoEls[domIdx].setAttribute('data-anno-source', source);
            annoEls[domIdx].style.setProperty('--anno-clr', color);
            annoEls[domIdx].removeAttribute('data-anno-idx-cleared');
            if (s2 > 0) annoEls[domIdx].setAttribute('data-anno-cont', '1');
            else annoEls[domIdx].removeAttribute('data-anno-cont');
            domIdx++;
        }
    }

    for (; domIdx < annoEls.length; domIdx++) clearAnnoEl(annoEls[domIdx]);
}

/**
 * Text-based mapping for XML-derived references.
 * For each reference element find the DOM block whose text best prefix-matches
 * ref.text_start, then claim that block plus span-1 following unused blocks.
 * _extra_pdf and _unmatched_xml have no DOCX counterpart -> skipped.
 */
function _syncHtmlElementsText(annoEls) {
    var referenceData = getReferenceData();

    // Pre-clear all blocks
    for (var ci = 0; ci < annoEls.length; ci++) clearAnnoEl(annoEls[ci]);

    // Pre-compute normalized texts for all DOM elements
    var domNorms = [];
    for (var di = 0; di < annoEls.length; di++) {
        domNorms.push(normForMatch(getCleanText(annoEls[di])));
    }

    var usedDom = [];
    for (var ui = 0; ui < annoEls.length; ui++) usedDom.push(false);

    var refElems = referenceData.elements;

    for (var r = 0; r < refElems.length; r++) {
        var refElem = refElems[r];
        var type = refElem.type;

        // Types without a real DOCX block: skip
        if (type === '_skip' || type === '_extra_pdf' || type === '_unmatched_xml') continue;

        var textStart = normForMatch(refElem.text_start || '');
        if (!textStart) continue;

        // Find DOM element with best prefix-match to text_start
        var bestIdx = -1;
        var bestScore = 0;
        for (var di2 = 0; di2 < annoEls.length; di2++) {
            if (usedDom[di2]) continue;
            var domText = domNorms[di2];
            var len = Math.min(textStart.length, domText.length);
            var pfx = 0;
            for (var ci2 = 0; ci2 < len; ci2++) {
                if (textStart[ci2] !== domText[ci2]) break;
                pfx++;
            }
            var score = textStart.length > 0 ? pfx / textStart.length : 0;
            if (score > bestScore) { bestScore = score; bestIdx = di2; }
        }

        if (bestIdx < 0 || bestScore < 0.3) continue; // no acceptable match

        var span = refElem.span || 1;
        var idx = refElem.idx;
        var color = getAnnoColor(idx);
        var source = refElem.type_source || 'auto';

        // Claim span blocks: anchor + (span-1) next unused in DOM order
        var claimed = 0;
        for (var si = bestIdx; si < annoEls.length && claimed < span; si++) {
            if (usedDom[si]) continue;
            usedDom[si] = true;
            annoEls[si].setAttribute('data-anno-idx', String(idx));
            annoEls[si].setAttribute('data-anno-type', type);
            annoEls[si].setAttribute('data-anno-source', source);
            annoEls[si].style.setProperty('--anno-clr', color);
            annoEls[si].removeAttribute('data-anno-idx-cleared');
            if (claimed > 0) annoEls[si].setAttribute('data-anno-cont', '1');
            else annoEls[si].removeAttribute('data-anno-cont');
            claimed++;
        }
    }
}
