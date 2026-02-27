/**
 * edit-mode.js — Reference editing: context menu, CRUD operations,
 * merge/split/delete/create, and button handlers.
 *
 * This is the largest module — it handles the interactive editing
 * workflow for the reference markup (etalon).
 */

import { ANNO_TYPE_LABELS, SENTINEL_TYPES } from './config.js';
import { dom } from './state.js';
import * as state from './state.js';
import { normType, getCleanText, filterTopLevel, getMarkerPage, markerTopToAbsolute } from './utils.js';
import { log } from './logger.js';
import { getAnnoColor, rebuildBadges, injectBadges, recalcMaxIdx, updatePosition } from './badges.js';
import { syncS1000dElements } from './xml-sync.js';
import { navigateTo, toggleAnnotations } from './navigation.js';
import { runVerification, runVerifyLoop } from './verification.js';

// ── Reference CRUD ──────────────────────────────────────────────────

function loadReference() {
    if (state.isEditMode()) return;
    var dmc = window.DMC_STRING;
    if (!dmc) return;

    fetch('/api/reference/' + dmc)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.exists) {
                state.setReferenceData(data.reference);
                enterEditMode();
            } else {
                // Init from auto
                fetch('/api/reference/' + dmc + '/init', { method: 'POST' })
                    .then(function (r) { return r.json(); })
                    .then(function (data2) {
                        if (data2.reference) {
                            state.setReferenceData(data2.reference);
                            enterEditMode();
                        }
                    });
            }
        });
}

export function enterEditMode() {
    state.setEditMode(true);
    document.body.classList.add('ref-editing');
    if (dom.saveRefBtn) dom.saveRefBtn.style.display = '';
    if (dom.resetRefBtn) dom.resetRefBtn.style.display = '';
    if (dom.verifyBtn) dom.verifyBtn.style.display = '';
    if (dom.loopBtn) dom.loopBtn.style.display = '';
    if (dom.editRefBtn) dom.editRefBtn.classList.add('active');

    // Make sure annotations are visible
    if (!state.isAnnotationsVisible()) {
        toggleAnnotations();
    }

    // Sync badges with referenceData (applies saved user changes)
    rebuildBadges(dom.docxPanel);
    // Sync right panel indices to match reference and rebuild badges
    syncS1000dElements();
    // Remove stale badges (injected before reference was loaded)
    var oldBadges = dom.s1000dPanel.querySelectorAll('.anno-badge');
    for (var bi = oldBadges.length - 1; bi >= 0; bi--) {
        oldBadges[bi].parentNode.removeChild(oldBadges[bi]);
    }
    injectBadges(dom.s1000dPanel);
    recalcMaxIdx();
    updatePosition();
}

function exitEditMode() {
    state.setEditMode(false);
    document.body.classList.remove('ref-editing');
    if (dom.saveRefBtn) dom.saveRefBtn.style.display = 'none';
    if (dom.resetRefBtn) dom.resetRefBtn.style.display = 'none';
    if (dom.verifyBtn) dom.verifyBtn.style.display = 'none';
    if (dom.loopBtn) dom.loopBtn.style.display = 'none';
    if (dom.editRefBtn) dom.editRefBtn.classList.remove('active');
    hideContextMenu();
}

function saveReference() {
    var referenceData = state.getReferenceData();
    if (!referenceData || !window.DMC_STRING) {
        console.warn('[edit-mode] saveReference: no referenceData or DMC_STRING', {
            hasRef: !!referenceData, dmc: window.DMC_STRING
        });
        return;
    }

    var payload = {
        elements: referenceData.elements,
        source: 'auto+manual'
    };
    console.log('[edit-mode] saveReference: sending', payload.elements.length, 'elements to', '/api/reference/' + window.DMC_STRING);

    fetch('/api/reference/' + window.DMC_STRING, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(function (r) {
        console.log('[edit-mode] saveReference: response status', r.status);
        return r.json();
    })
    .then(function (data) {
        if (data.reference) {
            console.log('[edit-mode] saveReference: saved OK,', data.reference.elements.length, 'elements');
            state.setReferenceData(data.reference);
            // Rebuild badges to reflect any changes
            rebuildBadges(dom.docxPanel);
            // Flash save button
            if (dom.saveRefBtn) {
                dom.saveRefBtn.textContent = '\u2713 \u0421\u043E\u0445\u0440.';
                setTimeout(function () { dom.saveRefBtn.textContent = '\u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C'; }, 1500);
            }
        } else {
            console.error('[edit-mode] saveReference: no reference in response', data);
        }
    })
    .catch(function (err) {
        console.error('[edit-mode] saveReference: fetch error', err);
    });
}

// ── Context menu ────────────────────────────────────────────────────

function showContextMenu(idx, x, y) {
    if (!dom.contextMenu) return;

    var referenceData = state.getReferenceData();
    state.setCtxTargetIdx(idx);
    var elem = referenceData ? findRefElement(idx) : null;

    // If reference doesn't have this idx, build a fallback from the DOM annotation
    if (!elem) {
        var domEl = dom.docxPanel.querySelector('[data-anno-idx="' + idx + '"]');
        var type = domEl ? (domEl.getAttribute('data-anno-type') || 'para') : 'para';
        // Prefer data-anno-text (PDF markers) over textContent (which includes labels)
        var textContent = domEl ? (domEl.getAttribute('data-anno-text') || domEl.textContent || '').substring(0, 80) : '';
        elem = { idx: idx, type: type, text_start: textContent, text_end: '' };
        // Add to reference if it exists, so edits can be saved
        if (referenceData) {
            referenceData.elements.push(elem);
            referenceData.elements.sort(function (a, b) { return a.idx - b.idx; });
        }
    }

    // Normalize legacy 'list' type to 'unnumbered_list'
    if (elem.type === 'list') elem.type = 'unnumbered_list';

    // Position menu
    dom.contextMenu.style.display = 'block';
    dom.contextMenu.style.left = Math.min(x, window.innerWidth - 250) + 'px';
    dom.contextMenu.style.top = Math.min(y, window.innerHeight - 250) + 'px';

    // Fill fields
    var nt = normType(elem.type);
    if (dom.ctxLabel) dom.ctxLabel.textContent = (ANNO_TYPE_LABELS[nt] || nt) + ' ' + elem.idx;
    if (dom.ctxTypeSelect) {
        dom.ctxTypeSelect.value = elem.type;

        // Enable/disable nested list options based on previous element type
        var prevIsListType = false;
        if (referenceData && referenceData.elements) {
            var arrIdx = findRefElementIndex(idx);
            if (arrIdx > 0) {
                var prevType = referenceData.elements[arrIdx - 1].type;
                prevIsListType = (prevType === 'numbered_list' || prevType === 'unnumbered_list' ||
                                 prevType === 'nested_unnumbered_list' || prevType === 'nested_numbered_list');
            }
        }
        var nestedOpts = dom.ctxTypeSelect.querySelectorAll('option[value^="nested_"]');
        for (var ni = 0; ni < nestedOpts.length; ni++) {
            nestedOpts[ni].disabled = !prevIsListType;
        }
    }
    if (dom.ctxPreview) {
        // Read actual text from DOM blocks for accurate preview
        var span = elem.span || 1;
        var subTexts = _collectSubTexts(elem.idx, span);
        var firstLine = (subTexts.length > 0 ? subTexts[0] : elem.text_start) || '';
        var lastLine = (subTexts.length > 1 ? subTexts[subTexts.length - 1] : '') || '';
        if (!lastLine || lastLine === firstLine) {
            dom.ctxPreview.textContent = firstLine;
        } else {
            dom.ctxPreview.textContent = firstLine + '\n\u2026\n' + lastLine;
        }
    }

    // Restore normal edit buttons, hide create button
    if (dom.ctxMergePrev) dom.ctxMergePrev.style.display = '';
    if (dom.ctxMergeNext) dom.ctxMergeNext.style.display = '';
    if (dom.ctxDelete) dom.ctxDelete.style.display = '';
    if (dom.ctxCreate) dom.ctxCreate.style.display = 'none';

    // Show/hide split button based on span
    if (dom.ctxSplit) {
        if (elem && (elem.span || 1) > 1) {
            dom.ctxSplit.style.display = '';
            dom.ctxSplit.textContent = '\u21B3 \u0420\u0430\u0437\u0434\u0435\u043B\u0438\u0442\u044C (' + (elem.span) + ')';
        } else {
            dom.ctxSplit.style.display = 'none';
        }
    }
}

function hideContextMenu() {
    if (dom.contextMenu) dom.contextMenu.style.display = 'none';
    state.setCtxTargetIdx(-1);
}

export function findRefElement(idx) {
    var referenceData = state.getReferenceData();
    if (!referenceData) return null;
    for (var i = 0; i < referenceData.elements.length; i++) {
        if (referenceData.elements[i].idx === idx) return referenceData.elements[i];
    }
    return null;
}

export function findRefElementIndex(idx) {
    var referenceData = state.getReferenceData();
    if (!referenceData) return -1;
    for (var i = 0; i < referenceData.elements.length; i++) {
        if (referenceData.elements[i].idx === idx) return i;
    }
    return -1;
}

function updateBadgeForElement(idx, newType) {
    var nt = normType(newType);
    var label = (ANNO_TYPE_LABELS[nt] || nt) + ' ' + idx;

    // Update HTML badges (.anno-badge-start)
    var badges = dom.docxPanel.querySelectorAll('[data-badge-idx="' + idx + '"]');
    for (var i = 0; i < badges.length; i++) {
        var badge = badges[i];
        if (badge.classList.contains('anno-badge-start')) {
            badge.textContent = label;
        }
    }
    // Update PDF markers (.anno-marker) — use child .marker-label if present
    var markers = dom.docxPanel.querySelectorAll('.anno-marker[data-anno-idx="' + idx + '"]');
    for (var j = 0; j < markers.length; j++) {
        var labelEl = markers[j].querySelector('.marker-label');
        if (labelEl) {
            labelEl.textContent = label;
        } else {
            markers[j].textContent = label;
        }
    }
    // Update the element's data-anno-type
    var el = dom.docxPanel.querySelector('[data-anno-idx="' + idx + '"]');
    if (el) el.setAttribute('data-anno-type', newType);
}

// ── Merge/Split/Delete helpers ──────────────────────────────────────

/** Find index of nearest non-sentinel element before arrIdx. */
function _findPrevReal(arrIdx) {
    var referenceData = state.getReferenceData();
    for (var i = arrIdx - 1; i >= 0; i--) {
        if (!SENTINEL_TYPES[referenceData.elements[i].type]) return i;
    }
    return -1;
}

/** Find index of nearest non-sentinel element after arrIdx. */
function _findNextReal(arrIdx) {
    var referenceData = state.getReferenceData();
    for (var i = arrIdx + 1; i < referenceData.elements.length; i++) {
        if (!SENTINEL_TYPES[referenceData.elements[i].type]) return i;
    }
    return -1;
}

function _collectSubTexts(idx, span) {
    var texts = [];
    var isPdf = window.RENDER_MODE === 'pdf';

    if (isPdf) {
        // PDF mode: collect from all markers (including hidden span markers)
        var allMarkers = dom.docxPanel.querySelectorAll('.anno-marker');
        var sorted = [];
        for (var i = 0; i < allMarkers.length; i++) sorted.push(allMarkers[i]);

        // Find the position of the first marker with this idx
        var startPos = -1;
        for (var i = 0; i < sorted.length; i++) {
            var mIdx = parseInt(sorted[i].getAttribute('data-anno-idx'), 10);
            if (mIdx === idx) { startPos = i; break; }
        }
        if (startPos < 0) return texts;

        for (var s = 0; s < span && (startPos + s) < sorted.length; s++) {
            var t = sorted[startPos + s].getAttribute('data-anno-text') || '';
            texts.push(t);
        }
    } else {
        // HTML mode: collect from top-level blocks
        var allAnno = dom.docxPanel.querySelectorAll('[data-anno-idx]');
        var annoEls = filterTopLevel(allAnno, dom.docxPanel);

        // Find first block with this idx
        var startPos = -1;
        for (var i = 0; i < annoEls.length; i++) {
            var bIdx = parseInt(annoEls[i].getAttribute('data-anno-idx'), 10);
            if (bIdx === idx) { startPos = i; break; }
        }
        if (startPos < 0) return texts;

        for (var s = 0; s < span && (startPos + s) < annoEls.length; s++) {
            texts.push(getCleanText(annoEls[startPos + s]));
        }
    }
    return texts;
}

function splitElement(idx) {
    var referenceData = state.getReferenceData();
    var arrIdx = findRefElementIndex(idx);
    if (arrIdx < 0) return;
    var elem = referenceData.elements[arrIdx];
    var span = elem.span || 1;
    if (span <= 1) return;

    var subTexts = _collectSubTexts(idx, span);
    var newElems = [];
    for (var s = 0; s < span; s++) {
        var t = subTexts[s] || '';
        newElems.push({
            idx: 0, type: elem.type,
            text_start: t.substring(0, 60),
            text_end: t.substring(Math.max(0, t.length - 40)),
            span: 1
        });
    }
    // ES5-safe splice to replace one element with multiple
    Array.prototype.splice.apply(referenceData.elements, [arrIdx, 1].concat(newElems));
    renumberRefElements();
    hideContextMenu();
    rebuildBadges(dom.docxPanel);
}

// ── Create element ──────────────────────────────────────────────────

function _determineInsertPosition(domPosition) {
    var referenceData = state.getReferenceData();
    if (!referenceData || !referenceData.elements.length) return 0;
    // Only count elements that actually consume markers
    // (skip sentinel types that have no PDF marker)
    var cumulative = 0;
    for (var i = 0; i < referenceData.elements.length; i++) {
        var t = referenceData.elements[i].type;
        if (SENTINEL_TYPES[t]) continue;
        cumulative += (referenceData.elements[i].span || 1);
        if (cumulative > domPosition) return i;
    }
    return referenceData.elements.length;
}

function showCreateMenu(block, domPosition, x, y) {
    if (!dom.contextMenu) return;

    state.setCreateBlock(block);
    state.setCreateDomPosition(domPosition);
    state.setCtxTargetIdx(-999); // special marker for create mode

    dom.contextMenu.style.display = 'block';
    dom.contextMenu.style.left = Math.min(x, window.innerWidth - 250) + 'px';
    dom.contextMenu.style.top = Math.min(y, window.innerHeight - 250) + 'px';

    if (dom.ctxLabel) dom.ctxLabel.textContent = '\u0421\u043E\u0437\u0434\u0430\u0442\u044C \u044D\u043B\u0435\u043C\u0435\u043D\u0442';
    if (dom.ctxTypeSelect) dom.ctxTypeSelect.value = 'para';
    if (dom.ctxPreview) dom.ctxPreview.textContent = block.getAttribute('data-anno-text') || getCleanText(block) || '';

    // Hide normal edit buttons, show cancel button (was "Создать")
    if (dom.ctxMergePrev) dom.ctxMergePrev.style.display = 'none';
    if (dom.ctxMergeNext) dom.ctxMergeNext.style.display = 'none';
    if (dom.ctxDelete) dom.ctxDelete.style.display = 'none';
    if (dom.ctxSplit) dom.ctxSplit.style.display = 'none';
    if (dom.ctxCreate) dom.ctxCreate.style.display = '';
}

export function renumberRefElements() {
    var referenceData = state.getReferenceData();
    var num = 0;
    for (var i = 0; i < referenceData.elements.length; i++) {
        if (referenceData.elements[i].type === '_skip') {
            referenceData.elements[i].idx = 0;
        } else {
            num++;
            referenceData.elements[i].idx = num;
        }
    }
}

/** Initialize edit mode event listeners */
export function initEditMode() {
    // Context menu: change type
    if (dom.ctxTypeSelect) {
        dom.ctxTypeSelect.addEventListener('change', function () {
            var referenceData = state.getReferenceData();
            if (state.getCtxTargetIdx() < 1 || !referenceData) return;
            var elem = findRefElement(state.getCtxTargetIdx());
            if (elem) {
                elem.type = dom.ctxTypeSelect.value;
                elem.type_source = 'user_override';
                updateBadgeForElement(state.getCtxTargetIdx(), dom.ctxTypeSelect.value);
                var updNt = normType(elem.type);
                if (dom.ctxLabel) dom.ctxLabel.textContent = (ANNO_TYPE_LABELS[updNt] || updNt) + ' ' + elem.idx;
                rebuildBadges(dom.docxPanel);
            }
        });
    }

    // Context menu: merge with previous
    if (dom.ctxMergePrev) {
        dom.ctxMergePrev.addEventListener('click', function () {
            var referenceData = state.getReferenceData();
            if (state.getCtxTargetIdx() < 1 || !referenceData) return;
            var arrIdx = findRefElementIndex(state.getCtxTargetIdx());
            if (arrIdx <= 0) return;

            var prevIdx = _findPrevReal(arrIdx);
            if (prevIdx < 0) return;

            var prev = referenceData.elements[prevIdx];
            var curr = referenceData.elements[arrIdx];
            // Merge: extend prev boundaries to cover current, track span
            var absorbedSpan = 0;
            for (var bi = prevIdx + 1; bi < arrIdx; bi++) {
                absorbedSpan += (referenceData.elements[bi].span || 1);
            }
            prev.text_end = curr.text_end;
            prev.span = (prev.span || 1) + absorbedSpan + (curr.span || 1);
            // Remove all elements from prevIdx+1 to arrIdx (inclusive)
            referenceData.elements.splice(prevIdx + 1, arrIdx - prevIdx);

            renumberRefElements();
            hideContextMenu();
            rebuildBadges(dom.docxPanel);
            saveReference();
        });
    }

    // Context menu: merge with next
    if (dom.ctxMergeNext) {
        dom.ctxMergeNext.addEventListener('click', function () {
            var referenceData = state.getReferenceData();
            if (state.getCtxTargetIdx() < 1 || !referenceData) return;
            var arrIdx = findRefElementIndex(state.getCtxTargetIdx());
            if (arrIdx < 0) return;

            var nextIdx = _findNextReal(arrIdx);
            if (nextIdx < 0) return;

            var curr = referenceData.elements[arrIdx];
            var next = referenceData.elements[nextIdx];
            var absorbedSpan = 0;
            for (var bi = arrIdx + 1; bi < nextIdx; bi++) {
                absorbedSpan += (referenceData.elements[bi].span || 1);
            }
            curr.text_end = next.text_end;
            curr.span = (curr.span || 1) + absorbedSpan + (next.span || 1);
            referenceData.elements.splice(arrIdx + 1, nextIdx - arrIdx);

            renumberRefElements();
            hideContextMenu();
            rebuildBadges(dom.docxPanel);
            saveReference();
        });
    }

    // Context menu: delete (mark as _skip to preserve positional mapping)
    if (dom.ctxDelete) {
        dom.ctxDelete.addEventListener('click', function () {
            var referenceData = state.getReferenceData();
            if (state.getCtxTargetIdx() < 1 || !referenceData) return;
            var arrIdx = findRefElementIndex(state.getCtxTargetIdx());
            if (arrIdx < 0) return;

            referenceData.elements[arrIdx].type = '_skip';
            renumberRefElements();
            hideContextMenu();
            rebuildBadges(dom.docxPanel);
            saveReference();
        });
    }

    // Context menu: split
    if (dom.ctxSplit) {
        dom.ctxSplit.addEventListener('click', function () {
            if (state.getCtxTargetIdx() < 1 || !state.getReferenceData()) return;
            splitElement(state.getCtxTargetIdx());
        });
    }

    // Helper: create a new element from the current create-mode state.
    // Returns true if element was created, false if not possible.
    function _doCreateElement() {
        var referenceData = state.getReferenceData();
        if (!referenceData) return false;
        var type = dom.ctxTypeSelect ? dom.ctxTypeSelect.value : 'para';
        var text = '';
        var createBlock = state.getCreateBlock();
        if (createBlock) {
            // For PDF markers, textContent is just the label ("+"),
            // so prefer data-anno-text which holds the actual block text.
            text = createBlock.getAttribute('data-anno-text')
                || getCleanText(createBlock) || '';
        }
        var insertAt = _determineInsertPosition(state.getCreateDomPosition());
        // Capture marker position so _syncPdfMarkersBbox finds the
        // correct marker (not another one with identical text on a
        // different page).
        var _bbox = null;
        if (createBlock && createBlock.classList.contains('anno-marker')) {
            _bbox = {
                page: getMarkerPage(createBlock, dom.docxPanel),
                y0: markerTopToAbsolute(createBlock, dom.docxPanel)
            };
        }

        console.log('[edit-mode] Create element:', {
            type: type, text: text.substring(0, 60),
            insertAt: insertAt, bbox: _bbox,
            totalBefore: referenceData.elements.length
        });
        log('edit', 'Create element', {
            type: type, text: text.substring(0, 40),
            insertAt: insertAt, bbox: _bbox
        });

        var newElem = {
            idx: 0, type: type,
            text_start: text.substring(0, 60),
            text_end: text.substring(Math.max(0, text.length - 40)),
            span: 1,
            type_source: 'user_override'
        };
        if (_bbox) newElem.bbox = _bbox;
        referenceData.elements.splice(insertAt, 0, newElem);
        renumberRefElements();
        console.log('[edit-mode] After create: total elements =', referenceData.elements.length,
                    ', new elem idx =', newElem.idx);
        rebuildBadges(dom.docxPanel);
        return true;
    }

    // Context menu: cancel (close dialog without changes)
    if (dom.ctxCreate) {
        dom.ctxCreate.addEventListener('click', function () {
            hideContextMenu();
        });
    }

    // Click handler for unassigned blocks in edit mode
    dom.docxPanel.addEventListener('click', function (e) {
        if (!state.isEditMode() || !state.getReferenceData()) return;

        // Check for HTML unassigned blocks
        var clearedBlock = e.target.closest('[data-anno-idx-cleared]');
        // Check for PDF unassigned markers
        var unassignedMarker = e.target.closest('.anno-marker-unassigned');

        if (!clearedBlock && !unassignedMarker) return;

        e.stopPropagation();
        e.preventDefault();

        var block = clearedBlock || unassignedMarker;
        var domPosition = 0;

        if (clearedBlock) {
            // Compute position among all top-level blocks
            var allAnno = dom.docxPanel.querySelectorAll('[data-anno-idx], [data-anno-idx-cleared]');
            var topLevel = filterTopLevel(allAnno, dom.docxPanel);
            for (var i = 0; i < topLevel.length; i++) {
                if (topLevel[i] === clearedBlock) { domPosition = i; break; }
            }
        } else {
            // PDF: compute position among all markers
            var allMarkers = dom.docxPanel.querySelectorAll('.anno-marker');
            for (var i = 0; i < allMarkers.length; i++) {
                if (allMarkers[i] === unassignedMarker) { domPosition = i; break; }
            }
        }

        showCreateMenu(block, domPosition, e.clientX, e.clientY);
    }, true); // useCapture to intercept before other handlers

    // Context menu: save reference (auto-creates element if in create mode)
    if (dom.ctxSave) {
        dom.ctxSave.addEventListener('click', function () {
            // If in create mode (ctxTargetIdx === -999), auto-create element first
            if (state.getCtxTargetIdx() === -999) {
                if (!_doCreateElement()) {
                    console.warn('[edit-mode] ctxSave: auto-create failed');
                    hideContextMenu();
                    return;
                }
                // Reset create mode state
                state.setCtxTargetIdx(-1);
            }
            // Immediately rebuild badges to show pending changes
            rebuildBadges(dom.docxPanel);
            saveReference();
            dom.ctxSave.textContent = '\u2713 \u0421\u043E\u0445\u0440.';
            dom.ctxSave.classList.add('saved');
            setTimeout(function () {
                dom.ctxSave.textContent = '\uD83D\uDCBE \u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C';
                dom.ctxSave.classList.remove('saved');
            }, 1500);
            hideContextMenu();
        });
    }

    // Close context menu on outside click (but not when clicking a badge/marker)
    document.addEventListener('click', function (e) {
        if (dom.contextMenu && dom.contextMenu.style.display !== 'none') {
            if (!dom.contextMenu.contains(e.target) &&
                !e.target.closest('.anno-badge-start') &&
                !e.target.closest('.anno-marker')) {
                hideContextMenu();
            }
        }
    });

    // Hook badge/marker clicks in edit mode (capture phase)
    dom.docxPanel.addEventListener('click', function (e) {
        if (!state.isEditMode()) return;

        // Try HTML badge first, then PDF marker
        var badge = e.target.closest('.anno-badge-start');
        var marker = badge ? null : e.target.closest('.anno-marker');
        if (!badge && !marker) return;

        e.stopPropagation();
        e.preventDefault();
        e.stopImmediatePropagation();

        var idx;
        if (badge) {
            idx = parseInt(badge.getAttribute('data-badge-idx'), 10);
        } else {
            idx = parseInt(marker.getAttribute('data-anno-idx'), 10);
        }
        if (idx > 0) {
            showContextMenu(idx, e.clientX, e.clientY);
        }
    }, true);  // useCapture = true

    // Button handlers
    if (dom.editRefBtn) {
        dom.editRefBtn.addEventListener('click', function () {
            if (state.isEditMode()) {
                exitEditMode();
            } else {
                loadReference();
            }
        });
    }

    if (dom.saveRefBtn) {
        dom.saveRefBtn.addEventListener('click', saveReference);
    }

    if (dom.verifyBtn) {
        dom.verifyBtn.addEventListener('click', runVerification);
    }

    if (dom.loopBtn) {
        dom.loopBtn.addEventListener('click', runVerifyLoop);
    }

    if (dom.resetRefBtn) {
        dom.resetRefBtn.addEventListener('click', function () {
            if (!window.DMC_STRING) return;
            if (!confirm('\u0423\u0434\u0430\u043B\u0438\u0442\u044C \u0442\u0435\u043A\u0443\u0449\u0438\u0439 \u044D\u0442\u0430\u043B\u043E\u043D \u0438 \u0441\u043E\u0437\u0434\u0430\u0442\u044C \u0437\u0430\u043D\u043E\u0432\u043E \u0438\u0437 \u0430\u0432\u0442\u043E\u043C\u0430\u0442\u0438\u0447\u0435\u0441\u043A\u043E\u0439 \u0440\u0430\u0437\u043C\u0435\u0442\u043A\u0438?')) return;

            dom.resetRefBtn.disabled = true;
            dom.resetRefBtn.textContent = '...';

            fetch('/api/reference/' + window.DMC_STRING, { method: 'DELETE' })
                .then(function (r) { return r.json(); })
                .then(function () {
                    return fetch('/api/reference/' + window.DMC_STRING + '/init', { method: 'POST' });
                })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.reference) {
                        state.setReferenceData(data.reference);
                        rebuildBadges(dom.docxPanel);
                    }
                    dom.resetRefBtn.disabled = false;
                    dom.resetRefBtn.textContent = '\u0421\u0431\u0440\u043E\u0441\u0438\u0442\u044C \u044D\u0442\u0430\u043B\u043E\u043D';
                })
                .catch(function () {
                    dom.resetRefBtn.disabled = false;
                    dom.resetRefBtn.textContent = '\u0421\u0431\u0440\u043E\u0441\u0438\u0442\u044C \u044D\u0442\u0430\u043B\u043E\u043D';
                    alert('\u041E\u0448\u0438\u0431\u043A\u0430 \u043F\u0440\u0438 \u0441\u0431\u0440\u043E\u0441\u0435 \u044D\u0442\u0430\u043B\u043E\u043D\u0430');
                });
        });
    }
}

/** Auto-load reference if one already exists for this DMC */
export function autoLoadReference() {
    var dmc = window.DMC_STRING;
    if (!dmc) return;

    fetch('/api/reference/' + dmc)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.exists) {
                state.setReferenceData(data.reference);
                enterEditMode();
            }
        })
        .catch(function () { /* silently fail */ });
}
