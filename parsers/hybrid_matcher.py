"""
Hybrid PDF↔DOCX element matcher.

Combines PDF visual boundaries (bounding boxes, order) with DOCX semantic
types (headings, lists, tables, etc.) using text similarity as the bridge.

Tables and illustrations (invisible in PDF) are inserted from DOCX at
positions interpolated between neighbouring PDF blocks.
"""

import hashlib
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


# ---------------------------------------------------------------------------
# Stable element ID
# ---------------------------------------------------------------------------

def compute_element_id(page_num: int, y0: float, text: str) -> str:
    """
    Generate a stable 12-hex-char element identifier.

    Stable across re-renders because y0 is quantised to multiples of 10.
    Two blocks with identical text at different positions get different IDs.
    """
    y_rounded = int(round(y0, -1))
    prefix = text[:30].strip().lower() if text else ""
    raw = f"{page_num}|{y_rounded}|{prefix}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Unified element
# ---------------------------------------------------------------------------

@dataclass
class UnifiedElement:
    element_id: str
    idx: int
    type: str
    type_source: str          # 'ooxml', 'heuristic', 'pdf_heuristic', 'user_override'
    bbox: Dict[str, float]    # {page, x0, y0, x1, y1}
    text: str
    text_start: str = ""
    text_end: str = ""
    span: int = 1
    docx_para_idx: int = -1
    match_confidence: float = 0.0
    font_info: Optional[Dict] = None

    def to_dict(self) -> dict:
        d = {
            "element_id": self.element_id,
            "idx": self.idx,
            "type": self.type,
            "type_source": self.type_source,
            "bbox": self.bbox,
            "text": self.text,
            "text_start": self.text_start,
            "text_end": self.text_end,
            "span": self.span,
        }
        if self.docx_para_idx >= 0:
            d["docx_match"] = {
                "para_idx": self.docx_para_idx,
                "confidence": round(self.match_confidence, 3),
            }
        if self.font_info:
            d["font_info"] = self.font_info
        return d

    def to_legacy_element_dict(self) -> dict:
        """Convert to the dict format expected by assemble_content_for_section()."""
        return {
            "type": self.type,
            "content": self.text,
            "start_para": self.docx_para_idx if self.docx_para_idx >= 0 else 0,
            "end_para": self.docx_para_idx if self.docx_para_idx >= 0 else 0,
            "start_line": 0,
            "end_line": 0,
            "start_char": 0,
            "end_char": 0,
            "xml_example": "",
            "details": "",
            "_element_id": self.element_id,
        }


# ---------------------------------------------------------------------------
# Text-similarity helpers (same logic as elements_analyzer.py)
# ---------------------------------------------------------------------------

def prefix_score(ref_text: str, content_text: str) -> float:
    """Prefix-based similarity score."""
    if not ref_text or not content_text:
        return 0.0
    a = ref_text.strip()
    b = content_text.strip()
    min_len = min(len(a), len(b))
    if min_len == 0:
        return 0.0
    prefix_len = 0
    for i in range(min_len):
        if a[i] == b[i]:
            prefix_len += 1
        else:
            break
    if prefix_len < 3:
        return 0.0
    return prefix_len / max(len(a), 1)


def combined_score(ref_text_start: str, ref_text_end: str, content: str) -> float:
    """Score using both text_start and text_end."""
    content_start = content[:60].strip()
    content_end = content[-40:].strip() if len(content) > 40 else content.strip()
    start_sc = prefix_score(ref_text_start, content_start)
    if not ref_text_end or not ref_text_end.strip():
        return start_sc
    end_sc = prefix_score(ref_text_end, content_end)
    return start_sc * 0.7 + end_sc * 0.3


# ---------------------------------------------------------------------------
# Core matching
# ---------------------------------------------------------------------------

def _find_best_docx_match(
    pdf_text: str,
    docx_elements: list,
    cursor: int,
    used: set,
) -> Optional[int]:
    """Find best DOCX element matching a PDF block by text similarity."""
    if not pdf_text or not pdf_text.strip():
        return None

    pdf_start = pdf_text[:60].strip()
    pdf_end = pdf_text[-40:].strip() if len(pdf_text) > 40 else pdf_text.strip()
    min_threshold = 0.2 if len(pdf_start) < 10 else 0.3

    best_idx = None
    best_score = min_threshold

    # Window search: cursor-5 .. cursor+50
    search_start = max(0, cursor - 5)
    search_end = min(len(docx_elements), cursor + 50)

    for i in range(search_start, search_end):
        if i in used:
            continue
        content = docx_elements[i].get("content", "")
        score = combined_score(pdf_start, pdf_end, content)
        if score > best_score:
            best_score = score
            best_idx = i

    # Fallback: full scan
    if best_idx is None:
        for i in range(len(docx_elements)):
            if i in used:
                continue
            content = docx_elements[i].get("content", "")
            score = combined_score(pdf_start, pdf_end, content)
            if score > best_score:
                best_score = score
                best_idx = i

    return best_idx


def _classify_by_font(block: dict, median_font: float) -> str:
    """Fallback type classification from PDF font metrics."""
    import re
    _dash_re = re.compile(r'^[\-\u2013\u2014\u2212\u2022\u25CF\u25CB]')
    _num_re = re.compile(r'^\d+[\.\)]\s')

    fs = block.get("max_font_size", 12)
    txt = block.get("text", "").strip()

    if fs > median_font * 1.3:
        return "header"
    if _dash_re.match(txt) or _num_re.match(txt):
        return "unnumbered_list"
    return "paragraph"


def _normalize_for_match(text: str) -> str:
    """
    Strip leading bullet/number markers and normalise case so list items
    and headings match regardless of capitalisation.
    Preserves multi-level prefixes (3.1.2, 3.2.5) for disambiguation.
    Also collapses spaced-out letters like 'П р и м е ч а н и е' → 'Примечание'.
    """
    import re
    text = text.strip()
    # Remove bullet/dash markers
    text = re.sub(
        r'^[\-\u2013\u2014\u2212\u2022\u25CF\u25CB\u2023\u25AA\u25AB\u2043]+\s*', '', text
    )
    # Remove numbered-list prefix '1.' / '1)' / '1.2.'
    text = re.sub(r'^\d+[\.\)]\s+', '', text)
    # NOTE: multi-level prefixes like '3.1.2 ' are intentionally NOT stripped.
    # They distinguish list items with identical body text during forward expansion
    # boundary checks (see lines 345-365). The max(normalized, raw) safety net in
    # initial matching (lines 309-311) ensures no regression.
    text = text.lower()
    # Collapse spaced-out letters like 'п р и м е ч а н и е' → 'примечание'.
    # Split on whitespace and merge consecutive single-character alpha tokens.
    parts = text.split()
    merged: list = []
    i = 0
    while i < len(parts):
        if len(parts[i]) == 1 and parts[i].isalpha():
            j = i + 1
            while j < len(parts) and len(parts[j]) == 1 and parts[j].isalpha():
                j += 1
            if j > i + 1:
                merged.append(''.join(parts[i:j]))
                i = j
                continue
        merged.append(parts[i])
        i += 1
    text = ' '.join(merged)
    # Remove spaces before punctuation ('примечание : затяжку' → 'примечание: затяжку')
    import re as _re
    text = _re.sub(r'\s+([;:,\.])', r'\1', text)
    return text


def _is_page_footer(text: str) -> bool:
    """Return True if PDF block is a page header/footer (not document content)."""
    import re
    # Patterns like 'ДЕЙСТВИТЕЛЬНО: ВСЕ ... Стр. 201'
    if re.search(r'Стр\.\s*\d', text) and len(text) < 200:
        return True
    # Very short blocks that are just page numbers
    stripped = text.strip()
    if re.fullmatch(r'\d{1,4}', stripped):
        return True
    return False


_WC_KEYWORDS = frozenset([
    'внимание', 'предупреждение', 'предостережение', 'осторожно',
    'примечание', 'caution', 'warning', 'note',
])


def _type_context_factor(xml_type: str, pdf_text: str, pdf_norm: str) -> float:
    """
    Score multiplier based on XML element type vs PDF block content.

    Prevents warning/caution/note XML elements from matching ordinary
    section headings or body paragraphs that contain no warning/note keywords.
    For all other element types returns 1.0 (no effect on scoring).
    """
    if xml_type not in ('warning', 'caution', 'note'):
        return 1.0
    lower_raw = pdf_text.lower()
    lower_norm = pdf_norm.lower()
    if any(kw in lower_raw or kw in lower_norm for kw in _WC_KEYWORDS):
        return 1.0
    # PDF block has no warning/caution/note keywords → strong penalty
    return 0.1


def _match_xml_to_pdf_pass(
    xml_indices: list,
    xml_elements: list,
    stable_ids: list,
    pdf_blocks: list,
    used_pdf: set,
    cursor: int,
    median_gap: float,
    result: list,
    window: int = 80,
) -> int:
    """
    Single matching pass: for each XML element in xml_indices, find the best
    PDF block within [cursor-3 .. cursor+window].

    Returns updated cursor value.
    Appends to result in-place; inserts sentinel dicts for unmatched (type '_unmatched_xml').
    """
    for xi in xml_indices:
        xml_elem = xml_elements[xi]
        sid = stable_ids[xi] if xi < len(stable_ids) else ''
        xml_ts = xml_elem.text_start or ''
        xml_te = xml_elem.text_end or ''
        xml_ts_norm = _normalize_for_match(xml_ts)
        # Tables/figures: lower threshold because PDF text is structurally
        # different (column separators etc.) and text_end doesn't help much.
        if xml_elem.type in ('table', 'figure', 'illustration'):
            min_thresh = 0.18
        elif len(xml_ts_norm.strip()) < 10:
            min_thresh = 0.15
        else:
            min_thresh = 0.3

        best_pi = None
        best_score = min_thresh
        search_start = max(0, cursor - 3)
        search_end = min(len(pdf_blocks), cursor + window)

        for pi in range(search_start, search_end):
            if pi in used_pdf:
                continue
            pdf_text = pdf_blocks[pi].get('text', '')
            pdf_norm = _normalize_for_match(pdf_text)
            score = max(
                combined_score(xml_ts_norm, xml_te, pdf_norm),
                combined_score(xml_ts, xml_te, pdf_text),
            )
            score *= _type_context_factor(xml_elem.type, pdf_text, pdf_norm)
            if score > best_score:
                best_score = score
                best_pi = pi

        if best_pi is None:
            result.append({
                '_xi': xi,          # sentinel: xml element index
                'type': '_unmatched_xml',
            })
            continue

        # Forward expansion: claim adjacent blocks belonging to this XML element
        claimed = [best_pi]
        used_pdf.add(best_pi)
        anchor_x0 = pdf_blocks[best_pi]['x0']
        anchor_page = pdf_blocks[best_pi]['page_num']

        for _ in range(30):
            next_pi = claimed[-1] + 1
            if next_pi >= len(pdf_blocks) or next_pi in used_pdf:
                break
            next_block = pdf_blocks[next_pi]

            if next_block['page_num'] > anchor_page + 1:
                break

            if next_block['page_num'] == pdf_blocks[claimed[-1]]['page_num']:
                gap = next_block['y0'] - pdf_blocks[claimed[-1]]['y1']
                if gap > median_gap * 3:
                    break

            # Stop if any OTHER XML element owns this block with reasonable
            # confidence.  Checks ALL elements (not just xi+1..xi+15) so that
            # past elements (e.g. a warning at xi=3) can prevent a later element
            # (xi=63) from consuming their PDF block.
            nxt_text = next_block.get('text', '')
            nxt_norm = _normalize_for_match(nxt_text)
            should_stop = False
            for check_xi in range(len(xml_elements)):
                if check_xi == xi:
                    continue
                chk = xml_elements[check_xi]
                chk_norm = _normalize_for_match(chk.text_start or '')
                chk_score = max(
                    combined_score(chk_norm, chk.text_end or '', nxt_norm),
                    combined_score(chk.text_start or '', chk.text_end or '', nxt_text),
                )
                if chk_score > 0.4:
                    should_stop = True
                    break
            if should_stop:
                break

            # X-offset check: stop if horizontal position differs significantly,
            # UNLESS blocks are vertically close on the same page (line-wrap
            # within the same paragraph — e.g. "ДЕМОН-" / "ТИРОВАТЬ,...").
            if abs(next_block['x0'] - anchor_x0) > 40:
                same_page = (next_block['page_num']
                             == pdf_blocks[claimed[-1]]['page_num'])
                if same_page:
                    gap = next_block['y0'] - pdf_blocks[claimed[-1]].get('y1', 0)
                    if gap > median_gap * 1.5:
                        break  # far apart vertically → different element
                    # else: close vertically → same-paragraph wrap, allow
                else:
                    break  # cross-page + different x → stop

            claimed.append(next_pi)
            used_pdf.add(next_pi)

            if xml_te:
                te_norm = _normalize_for_match(xml_te)
                blk_norm = _normalize_for_match(next_block.get('text', ''))
                if prefix_score(te_norm, blk_norm) > 0.4:
                    break

        first_blk = pdf_blocks[claimed[0]]
        last_blk = pdf_blocks[claimed[-1]]
        merged_x0 = min(pdf_blocks[i]['x0'] for i in claimed)
        merged_x1 = max(pdf_blocks[i]['x1'] for i in claimed)

        elem_id = compute_element_id(
            first_blk['page_num'], first_blk['y0'],
            xml_ts or first_blk.get('text', ''),
        )
        result.append({
            '_xi': xi,
            'idx': xi + 1,
            'type': xml_elem.type,
            'type_source': 'xml_derived',
            'text_start': xml_ts or first_blk.get('text', '')[:60],
            'text_end': xml_te or last_blk.get('text', '')[-40:],
            'span': len(claimed),
            'element_id': elem_id,
            'stable_id': sid,
            'bbox': {
                'page': first_blk['page_num'],
                'x0': round(merged_x0, 1),
                'y0': round(first_blk['y0'], 1),
                'x1': round(merged_x1, 1),
                'y1': round(last_blk['y1'], 1),
            },
        })
        cursor = max(claimed) + 1

    return cursor


def match_xml_to_pdf(
    xml_elements: list,
    pdf_blocks: list,
    stable_ids: list,
) -> list:
    """
    XML-first matching: XML elements are anchors, PDF blocks provide visual positions.

    For each XML element, finds the best matching PDF block(s) by text similarity,
    merging adjacent blocks that belong to the same element (e.g., list items).

    Two-pass strategy:
    - Pass 1: window-based search preserving document order.
    - Pass 2: global scan for XML elements still unmatched after pass 1
              (handles warnings/cautions whose PDF position differs from XML order).

    Args:
        xml_elements: List[ElementInfo] from extract_xml_elements(xml_path).
        pdf_blocks:   Flat list from extract_pdf_blocks_full() pages.
                      Each block must have: text, x0, y0, x1, y1, page_num.
        stable_ids:   list[str] in xml_elements order (from sidecar JSON).

    Returns:
        List of reference element dicts ready for save_reference().
        Unmatched XML elements are included with type '_unmatched_xml'.
        Extra PDF blocks (no XML match) are appended as type '_extra_pdf'.
    """
    import statistics

    # Pre-filter page headers/footers — they are layout artifacts, not content
    content_blocks = [(pi, b) for pi, b in enumerate(pdf_blocks)
                      if not _is_page_footer(b.get('text', ''))]
    # Re-index: orig_pi → content_idx
    orig_to_content = {orig: ci for ci, (orig, _) in enumerate(content_blocks)}
    content_list = [b for _, b in content_blocks]

    if not content_list:
        result = []
        for xi, xml_elem in enumerate(xml_elements):
            sid = stable_ids[xi] if xi < len(stable_ids) else ''
            result.append({
                'idx': xi + 1,
                'type': '_unmatched_xml',
                'type_source': 'xml_derived',
                'text_start': xml_elem.text_start,
                'text_end': xml_elem.text_end,
                'span': 1,
                'element_id': '',
                'stable_id': sid,
            })
        return result

    # Typical vertical gap between consecutive content blocks
    y_gaps = []
    for i in range(1, len(content_list)):
        b_prev, b_curr = content_list[i - 1], content_list[i]
        if b_curr['page_num'] == b_prev['page_num']:
            gap = b_curr['y0'] - b_prev['y1']
            if 0 < gap < 50:
                y_gaps.append(gap)
    median_gap = statistics.median(y_gaps) if y_gaps else 10.0

    used_pdf: set = set()
    cursor = 0
    pass1_result: list = []

    # Pass 1: window-based (preserves document order)
    cursor = _match_xml_to_pdf_pass(
        list(range(len(xml_elements))),
        xml_elements, stable_ids, content_list,
        used_pdf, cursor, median_gap, pass1_result, window=80,
    )

    # Pass 2: cursor-free global scan for still-unmatched XML elements.
    # Each element searches independently across ALL unclaimed content blocks,
    # so cursor jumps from pass 1 cannot strand elements at beginning of document.
    unmatched_xi = [r['_xi'] for r in pass1_result if r['type'] == '_unmatched_xml']
    if unmatched_xi:
        pass2_by_xi: dict = {}
        for xi in unmatched_xi:
            xml_elem = xml_elements[xi]
            sid = stable_ids[xi] if xi < len(stable_ids) else ''
            xml_ts = xml_elem.text_start or ''
            xml_te = xml_elem.text_end or ''
            xml_ts_norm = _normalize_for_match(xml_ts)
            # Tables/figures: lower threshold because PDF text is structurally
            # different (column separators etc.) and text_end doesn't help much.
            if xml_elem.type in ('table', 'figure', 'illustration'):
                min_thresh = 0.18
            elif len(xml_ts_norm.strip()) < 10:
                min_thresh = 0.15
            else:
                min_thresh = 0.3

            best_ci = None
            best_score = min_thresh
            for ci in range(len(content_list)):
                if ci in used_pdf:
                    continue
                pdf_text = content_list[ci].get('text', '')
                pdf_norm = _normalize_for_match(pdf_text)
                score = max(
                    combined_score(xml_ts_norm, xml_te, pdf_norm),
                    combined_score(xml_ts, xml_te, pdf_text),
                )
                score *= _type_context_factor(xml_elem.type, pdf_text, pdf_norm)
                if score > best_score:
                    best_score = score
                    best_ci = ci

            if best_ci is None:
                continue

            # Forward expansion (same logic as pass 1)
            claimed2 = [best_ci]
            used_pdf.add(best_ci)
            anchor_x0 = content_list[best_ci]['x0']
            anchor_page = content_list[best_ci]['page_num']

            for _ in range(30):
                next_ci = claimed2[-1] + 1
                if next_ci >= len(content_list) or next_ci in used_pdf:
                    break
                nblk = content_list[next_ci]
                if nblk['page_num'] > anchor_page + 1:
                    break
                if nblk['page_num'] == content_list[claimed2[-1]]['page_num']:
                    gap = nblk['y0'] - content_list[claimed2[-1]]['y1']
                    if gap > median_gap * 3:
                        break
                # Stop if any OTHER XML element owns this block with
                # reasonable confidence (check ALL elements — Pass 2 order
                # does not follow document order).
                nblk_text = nblk.get('text', '')
                nblk_norm = _normalize_for_match(nblk_text)
                stop2 = False
                for check_xi in range(len(xml_elements)):
                    if check_xi == xi:
                        continue
                    chk = xml_elements[check_xi]
                    chk_norm = _normalize_for_match(chk.text_start or '')
                    chk_score = max(
                        combined_score(chk_norm, chk.text_end or '', nblk_norm),
                        combined_score(chk.text_start or '', chk.text_end or '', nblk_text),
                    )
                    if chk_score > 0.4:
                        stop2 = True
                        break
                if stop2:
                    break
                # X-offset check: stop if horizontal position differs
                # significantly, UNLESS blocks are vertically close on the
                # same page (line-wrap within the same paragraph).
                if abs(nblk['x0'] - anchor_x0) > 40:
                    same_page = (nblk['page_num']
                                 == content_list[claimed2[-1]]['page_num'])
                    if same_page:
                        x_gap = nblk['y0'] - content_list[claimed2[-1]].get('y1', 0)
                        if x_gap > median_gap * 1.5:
                            break  # far apart vertically → different element
                        # else: close vertically → same-paragraph wrap, allow
                    else:
                        break  # cross-page + different x → stop
                claimed2.append(next_ci)
                used_pdf.add(next_ci)
                if xml_te:
                    te_norm = _normalize_for_match(xml_te)
                    blk_norm = _normalize_for_match(nblk.get('text', ''))
                    if prefix_score(te_norm, blk_norm) > 0.4:
                        break

            first_blk2 = content_list[claimed2[0]]
            last_blk2 = content_list[claimed2[-1]]
            merged_x0 = min(content_list[i]['x0'] for i in claimed2)
            merged_x1 = max(content_list[i]['x1'] for i in claimed2)
            elem_id = compute_element_id(
                first_blk2['page_num'], first_blk2['y0'],
                xml_ts or first_blk2.get('text', ''),
            )
            pass2_by_xi[xi] = {
                '_xi': xi,
                'idx': xi + 1,
                'type': xml_elem.type,
                'type_source': 'xml_derived',
                'text_start': xml_ts or first_blk2.get('text', '')[:60],
                'text_end': xml_te or last_blk2.get('text', '')[-40:],
                'span': len(claimed2),
                'element_id': elem_id,
                'stable_id': sid,
                'bbox': {
                    'page': first_blk2['page_num'],
                    'x0': round(merged_x0, 1),
                    'y0': round(first_blk2.get('y0', 0), 1),
                    'x1': round(merged_x1, 1),
                    'y1': round(last_blk2.get('y1', 0), 1),
                },
            }

        # Replace _unmatched_xml sentinels in pass1_result
        for i, r in enumerate(pass1_result):
            if r['type'] == '_unmatched_xml':
                xi = r['_xi']
                if xi in pass2_by_xi:
                    pass1_result[i] = pass2_by_xi[xi]

    # Build final result: remove _xi sentinels, fill in placeholders for still-unmatched
    final: list = []
    for r in pass1_result:
        if r['type'] == '_unmatched_xml':
            xi = r['_xi']
            xml_elem = xml_elements[xi]
            sid = stable_ids[xi] if xi < len(stable_ids) else ''
            xml_ts = xml_elem.text_start or ''
            xml_te = xml_elem.text_end or ''
            if final:
                pbbox = final[-1].get('bbox', {})
                page = pbbox.get('page', 1)
                y0 = pbbox.get('y1', 0) + 2
                x0, x1 = pbbox.get('x0', 72.0), pbbox.get('x1', 540.0)
            else:
                page, x0, y0, x1 = 1, 72.0, 0.0, 540.0
            final.append({
                'idx': xi + 1,
                'type': '_unmatched_xml',
                'type_source': 'xml_derived',
                'text_start': xml_ts,
                'text_end': xml_te,
                'span': 1,
                'element_id': compute_element_id(page, y0, f'UNM:{xml_ts}'),
                'stable_id': sid,
                'bbox': {'page': page, 'x0': round(x0, 1), 'y0': round(y0, 1),
                         'x1': round(x1, 1), 'y1': round(y0 + 18, 1)},
            })
        else:
            entry = {k: v for k, v in r.items() if k != '_xi'}
            final.append(entry)

    # Append unclaimed content blocks as _extra_pdf
    for ci, block in enumerate(content_list):
        if ci in used_pdf:
            continue
        text = block.get('text', '')
        page = block.get('page_num', 1)
        final.append({
            'idx': len(final) + 1,
            'type': '_extra_pdf',
            'type_source': 'pdf_heuristic',
            'text_start': text[:60],
            'text_end': text[-40:] if len(text) > 40 else text,
            'span': 1,
            'element_id': compute_element_id(page, block.get('y0', 0), text),
            'stable_id': '',
            'bbox': {
                'page': page,
                'x0': round(block.get('x0', 72.0), 1),
                'y0': round(block.get('y0', 0), 1),
                'x1': round(block.get('x1', 540.0), 1),
                'y1': round(block.get('y1', 0), 1),
            },
        })

    # Re-number idx sequentially
    for i, elem in enumerate(final):
        elem['idx'] = i + 1

    return final


def match_pdf_to_docx(
    pdf_pages: list,
    docx_elements: list,
) -> List[UnifiedElement]:
    """
    Match PDF blocks to DOCX elements, producing a unified element list.

    Args:
        pdf_pages: Output of extract_pdf_blocks_full() — list of page dicts.
        docx_elements: Output of analyze_document_elements() — list of element dicts.

    Returns:
        List of UnifiedElement in visual order (PDF page-by-page, top-to-bottom).
    """
    # Flatten PDF blocks across pages, remembering page_num
    flat_blocks = []
    for page in pdf_pages:
        for block in page["blocks"]:
            flat_blocks.append({
                **block,
                "page_num": page["page_num"],
                "page_width": page["width"],
                "page_height": page["height"],
            })

    # Compute median font for fallback classification
    all_fonts = sorted(b["max_font_size"] for b in flat_blocks) if flat_blocks else [12]
    median_font = all_fonts[len(all_fonts) // 2]

    # Match each PDF block to a DOCX element
    used_docx = set()
    cursor = 0
    matched_docx_indices = set()
    unified: List[UnifiedElement] = []
    idx_counter = 0

    for block in flat_blocks:
        pdf_text = block["text"]

        # Table blocks detected by PyMuPDF find_tables() — assign type directly
        if block.get("is_table"):
            # Try to find matching DOCX table element nearby
            best_table = None
            for di in range(max(0, cursor - 2), min(len(docx_elements), cursor + 10)):
                if di in used_docx:
                    continue
                if docx_elements[di].get("type") == "table":
                    best_table = di
                    break
            if best_table is not None:
                used_docx.add(best_table)
                matched_docx_indices.add(best_table)
                cursor = best_table + 1
            elem_type = "table"
            type_source = "pdf_table_detect"
            confidence = 1.0
            best = best_table if best_table is not None else -1
        else:
            best = _find_best_docx_match(pdf_text, docx_elements, cursor, used_docx)
            if best is not None:
                docx_elem = docx_elements[best]
                used_docx.add(best)
                matched_docx_indices.add(best)
                cursor = best + 1

                elem_type = docx_elem.get("type", "paragraph")
                type_source = "ooxml"

                # Compute match confidence
                pdf_start = pdf_text[:60].strip()
                pdf_end = pdf_text[-40:].strip() if len(pdf_text) > 40 else pdf_text.strip()
                confidence = combined_score(
                    pdf_start, pdf_end, docx_elem.get("content", "")
                )
            else:
                # No DOCX match — classify from PDF font heuristics
                elem_type = _classify_by_font(block, median_font)
                type_source = "pdf_heuristic"
                confidence = 0.0
                best = -1

        idx_counter += 1
        text = pdf_text
        elem = UnifiedElement(
            element_id=compute_element_id(block["page_num"], block["y0"], text),
            idx=idx_counter,
            type=elem_type,
            type_source=type_source,
            bbox={
                "page": block["page_num"],
                "x0": round(block["x0"], 1),
                "y0": round(block["y0"], 1),
                "x1": round(block["x1"], 1),
                "y1": round(block["y1"], 1),
            },
            text=text,
            text_start=text[:60] if text else "",
            text_end=text[-40:] if text and len(text) > 40 else text or "",
            docx_para_idx=docx_elements[best].get("start_para", -1) if best >= 0 else -1,
            match_confidence=confidence,
            font_info={
                "max_size": block["max_font_size"],
                "is_bold": block.get("is_bold", False),
                "is_italic": block.get("is_italic", False),
            },
        )
        unified.append(elem)

    # Insert unmatched DOCX elements (tables, illustrations) between PDF blocks
    # These are elements that exist in DOCX but have no corresponding PDF text block
    unmatched_docx = []
    for i, elem in enumerate(docx_elements):
        if i not in matched_docx_indices:
            etype = elem.get("type", "paragraph")
            # Only insert structurally important elements
            if etype in ("table", "illustration", "warning", "caution"):
                unmatched_docx.append((i, elem))

    for docx_idx, docx_elem in unmatched_docx:
        # Find insertion position: after the last matched element whose docx_idx < docx_idx
        insert_after = 0
        for ui, ue in enumerate(unified):
            if ue.docx_para_idx >= 0 and ue.docx_para_idx < docx_elements[docx_idx].get("start_para", 0):
                insert_after = ui + 1

        # Interpolate bbox from surrounding elements
        prev_bbox = unified[insert_after - 1].bbox if insert_after > 0 else None
        next_bbox = unified[insert_after].bbox if insert_after < len(unified) else None

        if prev_bbox and next_bbox and prev_bbox["page"] == next_bbox["page"]:
            page = prev_bbox["page"]
            y0 = prev_bbox["y1"] + 1
            y1 = next_bbox["y0"] - 1
        elif prev_bbox:
            page = prev_bbox["page"]
            y0 = prev_bbox["y1"] + 1
            y1 = y0 + 20
        elif next_bbox:
            page = next_bbox["page"]
            y0 = max(0, next_bbox["y0"] - 20)
            y1 = next_bbox["y0"] - 1
        else:
            page = 1
            y0 = 0
            y1 = 20

        content = docx_elem.get("content", "")
        idx_counter += 1
        interp_elem = UnifiedElement(
            element_id=compute_element_id(page, y0, f"DOCX:{content}"),
            idx=idx_counter,
            type=docx_elem.get("type", "paragraph"),
            type_source="ooxml",
            bbox={"page": page, "x0": 72.0, "y0": round(y0, 1), "x1": 540.0, "y1": round(y1, 1)},
            text=content,
            text_start=content[:60] if content else "",
            text_end=content[-40:] if content and len(content) > 40 else content or "",
            docx_para_idx=docx_elem.get("start_para", -1),
            match_confidence=1.0,
        )
        unified.insert(insert_after, interp_elem)

    # Re-number idx sequentially
    for i, elem in enumerate(unified):
        elem.idx = i + 1

    return unified
