/**
 * mismatch.js — Mismatch detection, issue navigation, and LCS matching.
 *
 * Detects differences between left (PDF/DOCX) and right (S1000D) panel
 * annotations using stable_id matching and LCS fallback.
 * Manages issue-based navigation mode.
 */

import { dom } from './state.js';
import * as state from './state.js';
import { normTypeForOrder } from './utils.js';
import { _rebuildHooks, updatePosition } from './badges.js';
import { navigateTo } from './navigation.js';
import { _navHooks } from './navigation.js';

/**
 * Collect annotation types from a panel.
 * Returns array of {idx, type} sorted by idx.
 */
function collectAnnoTypes(panel) {
    var elements = panel.querySelectorAll('[data-anno-idx]');
    var seen = {};
    var list = [];
    for (var i = 0; i < elements.length; i++) {
        // Skip hidden markers and unassigned markers
        if (elements[i].style.display === 'none') continue;
        if (elements[i].classList.contains('anno-marker-unassigned')) continue;
        var idx = parseInt(elements[i].getAttribute('data-anno-idx'), 10);
        // Deduplicate: cross-page spans produce multiple visible markers
        if (seen[idx]) continue;
        seen[idx] = true;
        list.push({
            idx: idx,
            type: elements[i].getAttribute('data-anno-type') || 'para'
        });
    }
    list.sort(function (a, b) { return a.idx - b.idx; });
    return list;
}

/**
 * Detect mismatches between left and right panel annotations.
 * Updates the mismatch badge in the header.
 */
export function detectMismatchFn() {
    if (!dom.mismatchBadge) return;

    var leftTypes = collectAnnoTypes(dom.docxPanel);
    var rightTypes = collectAnnoTypes(dom.s1000dPanel);

    var leftCount = leftTypes.length;
    var rightCount = rightTypes.length;

    if (leftCount === 0 && rightCount === 0) {
        dom.mismatchBadge.style.display = 'none';
        return;
    }

    dom.mismatchBadge.style.display = 'inline-block';

    // S1000D XSD reordering: warning/caution float before para/table/figure.
    // Exclude them when checking element order — their movement is expected.
    var XSD_FLOAT_TYPES = { 'caution': true, 'warning': true };

    var leftFiltered = leftTypes.filter(function (e) { return !XSD_FLOAT_TYPES[e.type]; });
    var rightFiltered = rightTypes.filter(function (e) { return !XSD_FLOAT_TYPES[e.type]; });

    if (leftCount === rightCount) {
        // Check if non-floating types match in order (using normalized types)
        var orderMatch = leftFiltered.length === rightFiltered.length;
        if (orderMatch) {
            for (var i = 0; i < leftFiltered.length; i++) {
                if (normTypeForOrder(leftFiltered[i].type) !== normTypeForOrder(rightFiltered[i].type)) {
                    orderMatch = false;
                    break;
                }
            }
        }
        if (orderMatch) {
            dom.mismatchBadge.className = 'mismatch-badge ok';
            dom.mismatchBadge.textContent = '\u2713 ' + leftCount + ' \u044D\u043B\u0435\u043C.';  // ✓ N элем.
        } else {
            dom.mismatchBadge.className = 'mismatch-badge warn';
            dom.mismatchBadge.textContent = '\u26A0 \u041F\u043E\u0440\u044F\u0434\u043E\u043A \u0440\u0430\u0437\u043B\u0438\u0447. (' + leftCount + ')';
            highlightMismatches(leftTypes, rightTypes);
        }
    } else {
        dom.mismatchBadge.className = 'mismatch-badge warn';
        dom.mismatchBadge.textContent = '\u26A0 \u0421\u043B\u0435\u0432\u0430 ' + leftCount + ', \u0441\u043F\u0440\u0430\u0432\u0430 ' + rightCount;
        highlightMismatches(leftTypes, rightTypes);
    }
}

/**
 * Highlight elements that don't match between panels.
 * Uses stable_id (data-element-id) for content-based matching,
 * falls back to LCS on types for elements without IDs.
 *
 * Three highlight levels:
 *   - anno-mismatch (red): no corresponding element found
 *   - anno-type-mismatch (orange): content matches but type differs
 *   - (no class): full match
 */
function highlightMismatches(leftTypes, rightTypes) {
    // Build right-panel lookup by stable_id (data-element-id)
    var rightByEid = {};
    for (var i = 0; i < rightTypes.length; i++) {
        var el = dom.s1000dPanel.querySelector('[data-anno-idx="' + rightTypes[i].idx + '"]');
        var eid = el ? (el.getAttribute('data-element-id') || '') : '';
        if (eid) rightByEid[eid] = { pos: i, type: rightTypes[i].type, idx: rightTypes[i].idx };
    }

    // Build left-panel lookup by stable_id
    var leftByEid = {};
    for (var i = 0; i < leftTypes.length; i++) {
        var el = dom.docxPanel.querySelector('[data-anno-idx="' + leftTypes[i].idx + '"]');
        var eid = el ? (el.getAttribute('data-element-id') || '') : '';
        if (eid) leftByEid[eid] = { pos: i, type: leftTypes[i].type, idx: leftTypes[i].idx };
    }

    var leftMatched = {};
    var rightMatched = {};

    // Phase 1: Match by stable_id
    for (var eid in leftByEid) {
        if (rightByEid[eid]) {
            var li = leftByEid[eid].pos;
            var ri = rightByEid[eid].pos;
            leftMatched[li] = ri;
            rightMatched[ri] = li;

            // Check type match
            if (leftByEid[eid].type !== rightByEid[eid].type) {
                var lEl = dom.docxPanel.querySelector('[data-anno-idx="' + leftByEid[eid].idx + '"]');
                var rEl = dom.s1000dPanel.querySelector('[data-anno-idx="' + rightByEid[eid].idx + '"]');
                if (lEl) lEl.classList.add('anno-type-mismatch');
                if (rEl) rEl.classList.add('anno-type-mismatch');
            }
        }
    }

    // Phase 2: LCS fallback for unmatched elements
    var unmatchedLeft = [];
    var unmatchedRight = [];
    for (var i = 0; i < leftTypes.length; i++) {
        if (!(i in leftMatched)) unmatchedLeft.push(i);
    }
    for (var i = 0; i < rightTypes.length; i++) {
        if (!(i in rightMatched)) unmatchedRight.push(i);
    }

    if (unmatchedLeft.length > 0 && unmatchedRight.length > 0) {
        var ulSeq = unmatchedLeft.map(function (i) { return leftTypes[i].type; });
        var urSeq = unmatchedRight.map(function (i) { return rightTypes[i].type; });
        var lcsSet = computeLCS(ulSeq, urSeq);
        for (var ul in lcsSet.leftMatched) {
            leftMatched[unmatchedLeft[ul]] = unmatchedRight[lcsSet.leftMatched[ul]];
            rightMatched[unmatchedRight[lcsSet.leftMatched[ul]]] = unmatchedLeft[ul];
        }
    }

    // Mark unmatched elements as anno-mismatch (red)
    for (var i = 0; i < leftTypes.length; i++) {
        if (!(i in leftMatched)) {
            var el = dom.docxPanel.querySelector('[data-anno-idx="' + leftTypes[i].idx + '"]');
            if (el) el.classList.add('anno-mismatch');
        }
    }
    for (var i = 0; i < rightTypes.length; i++) {
        if (!(i in rightMatched)) {
            var el = dom.s1000dPanel.querySelector('[data-anno-idx="' + rightTypes[i].idx + '"]');
            if (el) el.classList.add('anno-mismatch');
        }
    }
}

/**
 * Compute LCS and return which indices in left/right are part of the match.
 */
function computeLCS(a, b) {
    var m = a.length;
    var n = b.length;

    // DP table
    var dp = [];
    for (var i = 0; i <= m; i++) {
        dp[i] = [];
        for (var j = 0; j <= n; j++) {
            dp[i][j] = 0;
        }
    }
    for (var i = 1; i <= m; i++) {
        for (var j = 1; j <= n; j++) {
            if (a[i - 1] === b[j - 1]) {
                dp[i][j] = dp[i - 1][j - 1] + 1;
            } else {
                dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
            }
        }
    }

    // Backtrack to find matched indices
    var leftMatched = {};
    var rightMatched = {};
    var i = m, j = n;
    while (i > 0 && j > 0) {
        if (a[i - 1] === b[j - 1]) {
            leftMatched[i - 1] = true;
            rightMatched[j - 1] = true;
            i--;
            j--;
        } else if (dp[i - 1][j] > dp[i][j - 1]) {
            i--;
        } else {
            j--;
        }
    }

    return { leftMatched: leftMatched, rightMatched: rightMatched };
}

// ====================================================================
// Issue navigation (расхождения)
// ====================================================================

/**
 * Check if two types are the same after normalization.
 */
function isNormalizedSame(t1, t2) {
    function n(t) {
        if (t === 'paragraph' || t === 'para') return 'para';
        if (t === 'illustration' || t === 'figure') return 'figure';
        if (t === 'numbered_list' || t === 'unnumbered_list'
            || t === 'nested_numbered_list' || t === 'nested_unnumbered_list') return 'list';
        if (t === 'heading' || t === 'header') return 'heading';
        return t;
    }
    var n1 = n(t1), n2 = n(t2);
    if (n1 === n2) return true;
    // Section-numbered lists generate <levelledPara> (heading) in XML
    if ((n1 === 'list' && n2 === 'heading') || (n1 === 'heading' && n2 === 'list')) return true;
    return false;
}

/**
 * Human-readable explanation for a type mismatch.
 */
function explainTypeMismatch(refType, xmlType) {
    if (refType.indexOf('nested_') === 0 &&
        (xmlType.indexOf('list') >= 0 || xmlType === 'unnumbered_list' || xmlType === 'numbered_list'))
        return '\u0422\u0438\u043F: \u0432\u043B\u043E\u0436\u0435\u043D\u043D\u044B\u0439 \u0441\u043F\u0438\u0441\u043E\u043A \u043F\u043E\u0433\u043B\u043E\u0449\u0451\u043D \u0440\u043E\u0434\u0438\u0442\u0435\u043B\u044C\u0441\u043A\u0438\u043C \u044D\u043B\u0435\u043C\u0435\u043D\u0442\u043E\u043C';
    if ((refType === 'caution' || refType === 'warning') && xmlType === 'para')
        return '\u0422\u0438\u043F: ' + refType + ' \u0432 \u044D\u0442\u0430\u043B\u043E\u043D\u0435 \u2192 para \u0432 XML (\u043D\u0435 \u0440\u0430\u0441\u043F\u043E\u0437\u043D\u0430\u043D \u043A\u0430\u043A \u043F\u0440\u0435\u0434\u0443\u043F\u0440\u0435\u0436\u0434\u0435\u043D\u0438\u0435)';
    if (refType === 'para' && (xmlType === 'caution' || xmlType === 'warning'))
        return '\u0422\u0438\u043F: para \u0432 \u044D\u0442\u0430\u043B\u043E\u043D\u0435 \u2192 ' + xmlType + ' \u0432 XML';
    return '\u0422\u0438\u043F: ' + refType + ' \u0432 \u044D\u0442\u0430\u043B\u043E\u043D\u0435 \u2260 ' + xmlType + ' \u0432 XML';
}

/**
 * Build issues list from a ComparisonReport (returned by /api/verify).
 * Each issue represents a factor reducing the score.
 */
export function buildIssuesList(report) {
    var issuesList = [];
    var SIM_THRESHOLD = 0.95;

    // 1. Unmatched reference elements (reduce match_ratio)
    (report.left_unmatched || []).forEach(function (idx) {
        issuesList.push({
            idx: idx, side: 'left', category: 'unmatched',
            explanation: '\u042D\u043B\u0435\u043C\u0435\u043D\u0442 \u044D\u0442\u0430\u043B\u043E\u043D\u0430 [' + idx + '] \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D \u0432 XML'
        });
    });

    // 2. Unmatched XML elements (reduce match_ratio)
    (report.right_unmatched || []).forEach(function (idx) {
        issuesList.push({
            idx: idx, side: 'right', category: 'unmatched',
            explanation: '\u042D\u043B\u0435\u043C\u0435\u043D\u0442 XML [' + idx + '] \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D \u0432 \u044D\u0442\u0430\u043B\u043E\u043D\u0435'
        });
    });

    // 3. Type mismatches (reduce type_ratio) — only non-normalized
    (report.type_mismatches || []).forEach(function (m) {
        var refIdx = m[0], xmlIdx = m[1], refType = m[2], xmlType = m[3];
        if (isNormalizedSame(refType, xmlType)) return;
        issuesList.push({
            idx: refIdx, side: 'both', category: 'type',
            explanation: explainTypeMismatch(refType, xmlType)
        });
    });

    // 4. Low text similarity (reduce avg_text_sim)
    var unmatchedSet = {};
    (report.left_unmatched || []).forEach(function (i) { unmatchedSet[i] = true; });

    (report.text_similarities || []).forEach(function (s) {
        var refIdx = s[0], xmlIdx = s[1], sim = s[2];
        if (sim >= SIM_THRESHOLD) return;
        if (unmatchedSet[refIdx]) return;  // already reported as unmatched
        var pct = (sim * 100).toFixed(0);
        issuesList.push({
            idx: refIdx, side: 'both', category: 'text',
            explanation: '\u0422\u0435\u043A\u0441\u0442\u043E\u0432\u043E\u0435 \u0441\u0445\u043E\u0434\u0441\u0442\u0432\u043E: ' + pct + '% (\u044D\u043B\u0435\u043C\u0435\u043D\u0442 [' + refIdx + '] \u2194 [' + xmlIdx + '])'
        });
    });

    // Sort by idx
    issuesList.sort(function (a, b) { return a.idx - b.idx; });

    // Merge issues sharing the same idx: combine explanations
    var merged = [];
    for (var i = 0; i < issuesList.length; i++) {
        var prev = merged.length > 0 ? merged[merged.length - 1] : null;
        if (prev && prev.idx === issuesList[i].idx) {
            prev.explanation += ' \u2502 ' + issuesList[i].explanation;  // │ separator
        } else {
            merged.push({
                idx: issuesList[i].idx,
                side: issuesList[i].side,
                category: issuesList[i].category,
                explanation: issuesList[i].explanation
            });
        }
    }
    state.setIssuesList(merged);
    state.setCurrentIssuePos(-1);
    updateNavUI();
}

function navigateToNextIssue() {
    var issuesList = state.getIssuesList();
    if (issuesList.length === 0) return;
    var pos = (state.getCurrentIssuePos() + 1) % issuesList.length;
    state.setCurrentIssuePos(pos);
    var issue = issuesList[pos];
    navigateTo(issue.idx);
    updateNavUI();
    showIssueTooltip(issue);
}

function navigateToPrevIssue() {
    var issuesList = state.getIssuesList();
    if (issuesList.length === 0) return;
    var pos = (state.getCurrentIssuePos() - 1 + issuesList.length) % issuesList.length;
    state.setCurrentIssuePos(pos);
    var issue = issuesList[pos];
    navigateTo(issue.idx);
    updateNavUI();
    showIssueTooltip(issue);
}

function updateNavUI() {
    if (!dom.positionSpan) return;
    var issuesList = state.getIssuesList();
    if (state.getNavMode() === 'issues') {
        if (issuesList.length === 0) {
            dom.positionSpan.textContent = '0 \u0440\u0430\u0441\u0445.';  // 0 расх.
        } else if (state.getCurrentIssuePos() < 0) {
            dom.positionSpan.textContent = '\u2014 / ' + issuesList.length + ' \u0440\u0430\u0441\u0445.';
        } else {
            dom.positionSpan.textContent = (state.getCurrentIssuePos() + 1) + ' / ' + issuesList.length + ' \u0440\u0430\u0441\u0445.';
        }
    } else {
        updatePosition();
        hideIssueTooltip();
    }
}

function showIssueTooltip(issue) {
    if (!dom.issueTooltip) return;
    var icons = { unmatched: '\u274C', type: '\uD83D\uDD36', text: '\uD83D\uDCCA' };
    dom.issueTooltip.textContent = (icons[issue.category] || '') + ' ' + issue.explanation;
    dom.issueTooltip.style.display = 'block';
}

function hideIssueTooltip() {
    if (dom.issueTooltip) dom.issueTooltip.style.display = 'none';
}

/** Initialize mismatch detection and issue navigation */
export function initMismatch() {
    // Register hooks
    _rebuildHooks.detectMismatch = detectMismatchFn;
    _navHooks.navigateToNextIssue = navigateToNextIssue;
    _navHooks.navigateToPrevIssue = navigateToPrevIssue;

    // Nav mode selector
    if (dom.navModeSelect) {
        dom.navModeSelect.addEventListener('change', function () {
            state.setNavMode(this.value);
            state.setCurrentIssuePos(-1);
            updateNavUI();
        });
    }
}
