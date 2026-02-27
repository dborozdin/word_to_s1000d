"""
Element comparison logic for docx ↔ S1000D XML.

Extraction (ElementInfo, ComparisonReport, extract_*) lives in
headless_extractor.py.  This module provides compare_elements() and
re-exports extraction symbols for backward compatibility.
"""

import re
import difflib
from typing import List, Tuple

# ── Re-exports for backward compatibility ──
# All existing `from comparison_app.headless_comparator import X` continue to work.
from comparison_app.headless_extractor import (   # noqa: F401
    ElementInfo,
    ComparisonReport,
    extract_docx_elements,
    extract_xml_elements,
)


# ==========================================================================
# LCS comparison (port from comparison.js)
# ==========================================================================

def _compute_lcs(a: list, b: list) -> Tuple[dict, dict]:
    """
    Compute LCS and return matched indices.
    Returns (left_matched, right_matched) where keys are 0-based indices.
    """
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    # Backtrack
    left_matched = {}
    right_matched = {}
    i, j = m, n
    while i > 0 and j > 0:
        if a[i - 1] == b[j - 1]:
            left_matched[i - 1] = j - 1
            right_matched[j - 1] = i - 1
            i -= 1
            j -= 1
        elif dp[i - 1][j] > dp[i][j - 1]:
            i -= 1
        else:
            j -= 1

    return left_matched, right_matched


def _norm_type(t: str) -> str:
    """Normalize element type for comparison (reduces false type mismatches)."""
    if t in ('paragraph', 'para'):
        return 'para'
    if t in ('illustration', 'figure', 'illustration_reference'):
        return 'figure'
    if t in ('numbered_list', 'unnumbered_list', 'nested_numbered_list', 'nested_unnumbered_list'):
        return 'list'
    if t in ('heading', 'header'):
        return 'heading'
    return t


def _types_compatible(t1: str, t2: str) -> bool:
    """Check if two element types are compatible for scoring.

    Beyond simple normalization, section-numbered lists in the reference
    generate <levelledPara><title> (heading) in XML — this is correct behavior.
    """
    n1, n2 = _norm_type(t1), _norm_type(t2)
    if n1 == n2:
        return True
    # numbered_list (reference) ↔ heading (XML) for section-numbered items
    if {n1, n2} == {'list', 'heading'}:
        return True
    return False


_NUM_PREFIX_RE = re.compile(r'^[\d]+(?:\.[\d]+)*\s+')
_FIGURE_PREFIX_RE = re.compile(r'^рисунок\s+\d+\s*[–—\-]\s*', re.IGNORECASE)
_DASH_PREFIX_RE = re.compile(r'^[–—\-]\s*')
_DEHYPHENATE_RE = re.compile(r'([а-яёa-z])-\s+([а-яёa-z])')
# PDF letter-spacing artifact: "П р и м е ч а н и е" → collapse single-char runs
_SPACED_LETTERS_RE = re.compile(r'(?<!\S)([\wа-яёА-ЯЁ]) ([\wа-яёА-ЯЁ]) ([\wа-яёА-ЯЁ])(?: ([\wа-яёА-ЯЁ]))*')


def _collapse_spaced_letters(text: str) -> str:
    """Collapse PDF letter-spacing artifacts: 'п р и м е ч а н и е' → 'примечание'."""
    # Known spaced words in Russian aviation docs
    text = text.replace('п р и м е ч а н и е', 'примечание')
    text = text.replace('в н и м а н и е', 'внимание')
    # Clean up "примечание :" → "примечание:"
    text = text.replace('примечание :', 'примечание:')
    return text


def _norm_text(text: str) -> str:
    """Normalize text for matching: lowercase, strip numbering/figure prefixes."""
    text = text.strip().lower()
    text = re.sub(r'\s+', ' ', text)  # collapse whitespace
    text = _collapse_spaced_letters(text)  # PDF letter-spacing
    text = _DEHYPHENATE_RE.sub(r'\1\2', text)  # PDF hyphenation: "про- мыть" → "промыть"
    text = _NUM_PREFIX_RE.sub('', text)
    text = _FIGURE_PREFIX_RE.sub('', text)
    text = _DASH_PREFIX_RE.sub('', text)
    return text


def compare_elements(left: List[ElementInfo], right: List[ElementInfo]) -> ComparisonReport:
    """
    Compare two element lists using content-based matching.

    Three-phase matching:
      1. Direct stable_id match (fast path when both sides have IDs)
      2. Content-based matching via text similarity for remaining elements
      3. LCS fallback on types for any still-unmatched elements

    Score formula: 40% match_ratio + 30% type_correctness + 30% text_similarity
    This is resilient to type misclassifications: a paragraph misclassified as
    a list still matches by text, and the type error is penalized separately.
    """
    report = ComparisonReport(
        left_count=len(left),
        right_count=len(right),
    )

    if not left and not right:
        report.score = 1.0
        return report

    if not left or not right:
        report.left_unmatched = [e.idx for e in left]
        report.right_unmatched = [e.idx for e in right]
        report.score = 0.0
        return report

    left_matched = {}   # left_index -> right_index
    right_matched = {}  # right_index -> left_index

    # --- Phase 1: Direct stable_id matching ---
    right_by_sid = {}
    for ri, elem in enumerate(right):
        if elem.stable_id:
            right_by_sid.setdefault(elem.stable_id, []).append(ri)

    for li, elem in enumerate(left):
        if elem.stable_id and elem.stable_id in right_by_sid:
            candidates = right_by_sid[elem.stable_id]
            for ri in candidates:
                if ri not in right_matched:
                    left_matched[li] = ri
                    right_matched[ri] = li
                    break

    # --- Phase 2: Content-based matching for remaining ---
    # Uses normalized text (lowercase, stripped numbering/figure prefixes)
    # to handle cases like "1 МЕРЫ БЕЗОПАСНОСТИ" ↔ "Меры безопасности".
    # Global best-first approach: collect all candidate pairs, sort by
    # similarity descending, and greedily assign best matches first.
    # This prevents earlier elements from "stealing" good matches.
    candidates = []
    for li, elem in enumerate(left):
        if li in left_matched:
            continue
        l_start = _norm_text(elem.text_start)
        l_full = _norm_text(elem.text_start + ' ' + elem.text_end)
        if not l_start and not l_full:
            continue
        for ri, r_elem in enumerate(right):
            if ri in right_matched:
                continue
            r_start = _norm_text(r_elem.text_start)
            r_full = _norm_text(r_elem.text_start + ' ' + r_elem.text_end)
            if not r_start and not r_full:
                continue
            # Use max of text_start similarity and full text similarity.
            # This handles span>1 elements where text_end may diverge
            # while text_start (the beginning) matches well.
            sim_start = difflib.SequenceMatcher(None, l_start, r_start).ratio() if l_start and r_start else 0
            sim_full = difflib.SequenceMatcher(None, l_full, r_full).ratio() if l_full and r_full else 0
            sim = max(sim_start, sim_full)
            if sim >= 0.35:
                candidates.append((sim, li, ri))

    candidates.sort(key=lambda x: -x[0])  # best similarity first
    for sim, li, ri in candidates:
        if li in left_matched or ri in right_matched:
            continue
        left_matched[li] = ri
        right_matched[ri] = li

    # --- Phase 3: LCS fallback for remaining unmatched (by normalized type) ---
    unmatched_left = [i for i in range(len(left)) if i not in left_matched]
    unmatched_right = [i for i in range(len(right)) if i not in right_matched]
    if unmatched_left and unmatched_right:
        ul_types = [_norm_type(left[i].type) for i in unmatched_left]
        ur_types = [_norm_type(right[i].type) for i in unmatched_right]
        lcs_l, lcs_r = _compute_lcs(ul_types, ur_types)
        for ul_pos, ur_pos in lcs_l.items():
            li = unmatched_left[ul_pos]
            ri = unmatched_right[ur_pos]
            left_matched[li] = ri
            right_matched[ri] = li

    # --- Phase 4: Implicit (substring) matching ---
    # For remaining unmatched ref elements, check if their text is contained
    # inside an already-matched XML element (e.g., nested list items absorbed
    # into a parent randomList).  These get a "partial" match: the pair is
    # recorded but with lower text similarity since it's a containment match.
    still_unmatched = [i for i in range(len(left)) if i not in left_matched]
    if still_unmatched:
        for li in still_unmatched:
            l_text = _norm_text(left[li].text_start)
            l_end = _norm_text(left[li].text_end)
            if not l_text or len(l_text) < 8:
                continue
            best_ri = None
            best_score = 0.0
            for ri in range(len(right)):
                r_full = _norm_text(right[ri].text_start + ' ' + right[ri].text_end)
                if not r_full:
                    continue
                # Check containment: ref text_end appears in xml text_end
                # (for nested lists: last nested item text == parent's text_end)
                if l_end and len(l_end) >= 8:
                    r_end = _norm_text(right[ri].text_end)
                    end_sim = difflib.SequenceMatcher(None, l_end, r_end).ratio()
                    if end_sim > best_score and end_sim >= 0.4:
                        best_score = end_sim
                        best_ri = ri
                # Also check word overlap (for middle-of-text matches)
                l_words = set(l_text.split())
                r_words = set(r_full.split())
                if len(l_words) >= 3:
                    overlap = len(l_words & r_words) / len(l_words)
                    if overlap > best_score and overlap >= 0.5:
                        best_score = overlap
                        best_ri = ri
            if best_ri is not None:
                left_matched[li] = best_ri
                # Note: right_matched[best_ri] may already exist (many-to-one)

    # --- Build report ---
    for li, ri in sorted(left_matched.items()):
        report.matched_pairs.append((left[li].idx, right[ri].idx))

        # Track type mismatches (using raw types for reporting)
        if left[li].type != right[ri].type:
            report.type_mismatches.append((
                left[li].idx, right[ri].idx,
                left[li].type, right[ri].type
            ))

        # Text similarity (on normalized text for fair comparison)
        # Normalize each part separately so ^-anchored patterns (figure prefix)
        # are stripped from both text_start and text_end.
        # Three strategies, take max:
        #   1. Combined text (good for long elements)
        #   2. Avg of start/end (good when truncation point differs)
        #   3. Best part when >=0.98 (absorbed/nested elements, PDF artifacts)
        l_ts = _norm_text(left[li].text_start)
        l_te = _norm_text(left[li].text_end)
        r_ts = _norm_text(right[ri].text_start)
        r_te = _norm_text(right[ri].text_end)
        # Strategy 1: combined text
        l_combined = (l_ts + ' ' + l_te).strip()
        r_combined = (r_ts + ' ' + r_te).strip()
        sim_combined = difflib.SequenceMatcher(None, l_combined, r_combined).ratio() if l_combined and r_combined else 0
        # Strategy 2: avg of start/end
        sim_ts = difflib.SequenceMatcher(None, l_ts, r_ts).ratio() if l_ts and r_ts else 0
        sim_te = difflib.SequenceMatcher(None, l_te, r_te).ratio() if l_te and r_te else 0
        parts = [s for s in (sim_ts, sim_te) if s > 0]
        sim_parts = sum(parts) / len(parts) if parts else 0
        # Strategy 3: if one part matches nearly perfectly, the text is present
        # (the other part differs due to truncation window or nested absorption)
        best_part = max(sim_ts, sim_te)
        sim_best = best_part if best_part >= 0.98 else 0
        sim = max(sim_combined, sim_parts, sim_best)
        if sim > 0:
            report.text_similarities.append((left[li].idx, right[ri].idx, round(sim, 3)))

    report.left_unmatched = [left[i].idx for i in range(len(left)) if i not in left_matched]
    report.right_unmatched = [right[i].idx for i in range(len(right)) if i not in right_matched]

    # --- Score: 40% match_ratio + 30% type_correctness + 30% text_similarity ---
    max_count = max(len(left), len(right))
    match_ratio = len(report.matched_pairs) / max_count if max_count > 0 else 0

    # Use normalized types for scoring: paragraph=para, illustration=figure, etc.
    type_correct = sum(1 for li, ri in left_matched.items()
                       if _types_compatible(left[li].type, right[ri].type))
    type_ratio = type_correct / len(left_matched) if left_matched else 0

    avg_text_sim = 0.0
    if report.text_similarities:
        avg_text_sim = sum(s for _, _, s in report.text_similarities) / len(report.text_similarities)

    report.score = round(0.4 * match_ratio + 0.3 * type_ratio + 0.3 * avg_text_sim, 3)

    return report
