"""
Match PDF text blocks directly to S1000D XML elements for procedural modules.

For procedural data modules (technology cards / ТК), the source DOCX is a table
with steps in cells. Standard hybrid matching (PDF→DOCX) fails because DOCX
analyzer can't extract text from table cells. Instead, we match PDF blocks
directly to rendered HTML annotations by text similarity.

Key insight: the S1000D renderer is the single source of truth for the right panel.
We parse its HTML output to get (idx, type, text) tuples and match PDF blocks to those.
"""

import hashlib
import re
from difflib import SequenceMatcher
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

# Re-use UnifiedElement from hybrid_matcher for output compatibility
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from parsers.hybrid_matcher import UnifiedElement


def _normalize(text: str) -> str:
    """Normalize text for comparison: lowercase, collapse whitespace.

    Strips ALL leading numbering patterns (e.g. "2.7  1.1.4 Подключите..." → "подключите...")
    because renderer prepends step numbers and original text has its own numbering.
    """
    text = re.sub(r'\s+', ' ', text.strip().lower())
    # Strip repeated leading number patterns: "2.7  1.1.4 " or "3.23  1.2.3 "
    text = re.sub(r'^(?:[\d.]+\s+)+', '', text)
    # Also strip leading dashes/bullets
    text = re.sub(r'^[\-\u2013\u2014\u2022]\s*', '', text)
    return text


def _text_similarity(a: str, b: str) -> float:
    """Compute text similarity between two strings."""
    na = _normalize(a)
    nb = _normalize(b)
    if not na or not nb:
        return 0.0
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) >= 15 and longer.startswith(shorter):
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _compute_element_id(idx: int, elem_type: str, text: str) -> str:
    """Generate stable element ID from content."""
    raw = f"{idx}|{elem_type}|{text[:60]}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]


class _AnnoHTMLParser(HTMLParser):
    """Parse rendered S1000D HTML to extract (idx, type, text) for each annotation."""

    def __init__(self):
        super().__init__()
        self.elements: List[Tuple[int, str, str]] = []  # (idx, type, text_snippet)
        self._current_idx = None
        self._current_type = None
        self._current_text = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        idx_str = d.get('data-anno-idx')
        if idx_str:
            # Flush previous
            if self._current_idx is not None:
                self._flush()
            self._current_idx = int(idx_str)
            self._current_type = d.get('data-anno-type', 'para')
            self._current_text = []
            self._depth = 1
        elif self._current_idx is not None:
            self._depth += 1

    def handle_endtag(self, tag):
        if self._current_idx is not None:
            self._depth -= 1
            if self._depth <= 0:
                self._flush()

    def handle_data(self, data):
        if self._current_idx is not None:
            self._current_text.append(data)

    def _flush(self):
        text = ' '.join(self._current_text).strip()[:120]
        self.elements.append((self._current_idx, self._current_type, text))
        self._current_idx = None
        self._current_type = None
        self._current_text = []
        self._depth = 0


def _extract_rendered_elements(xml_path: str) -> List[Tuple[int, str, str]]:
    """Extract (idx, type, text) from rendered S1000D HTML — single source of truth."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
    from s1000d_renderer import render_s1000d_to_html
    html = render_s1000d_to_html(xml_path)
    parser = _AnnoHTMLParser()
    parser.feed(html)
    if parser._current_idx is not None:
        parser._flush()
    return parser.elements


def match_pdf_to_xml(pdf_pages: List[Dict], xml_path: str) -> List[UnifiedElement]:
    """Match PDF text blocks to rendered XML annotations by text similarity.

    Args:
        pdf_pages: Output of extract_pdf_blocks_full(collapse_tables=False)
        xml_path: Path to generated S1000D XML file

    Returns:
        List of UnifiedElement with bbox from PDF and idx/type from renderer
    """
    rendered = _extract_rendered_elements(xml_path)
    if not rendered:
        return _fallback_from_pdf(pdf_pages)

    # Flatten PDF blocks with page info
    pdf_blocks = []
    for page in pdf_pages:
        for block in page['blocks']:
            pdf_blocks.append({
                **block,
                'page_num': page['page_num'],
                'page_width': page['width'],
                'page_height': page['height'],
            })

    # Two-pass matching:
    # Pass 1: High-confidence global scan to anchor key elements
    # Pass 2: Sequential fill between anchors
    #
    # The rendered list contains preliminaryRqmts elements (headings, tables)
    # that don't exist in PDF-ТК. We skip them and match procedural steps.

    n_pdf = len(pdf_blocks)
    used_pdf = [False] * n_pdf
    matches = {}  # r_idx → (pdf_idx, score, block)

    # Pass 1: High-confidence matches (score > 0.7) — global scan
    for r_idx, r_type, r_text in rendered:
        if not r_text.strip():
            continue
        best_pi = -1
        best_score = 0.7
        for pi in range(n_pdf):
            if used_pdf[pi]:
                continue
            score = _text_similarity(r_text, pdf_blocks[pi].get('text', ''))
            if score > best_score:
                best_score = score
                best_pi = pi
        if best_pi >= 0:
            used_pdf[best_pi] = True
            matches[r_idx] = (best_pi, best_score, pdf_blocks[best_pi])

    # Pass 2: Fill gaps — for unmatched rendered elements, search near
    # the expected position (interpolated from neighboring anchors)
    anchor_positions = sorted(matches.keys())

    for r_idx, r_type, r_text in rendered:
        if r_idx in matches or not r_text.strip():
            continue

        # Find expected PDF position from neighbors
        prev_pi = -1
        next_pi = n_pdf
        for a in anchor_positions:
            if a < r_idx:
                prev_pi = matches[a][0]
            elif a > r_idx:
                next_pi = matches[a][0]
                break

        # Search in range [prev_pi+1 .. next_pi-1] with moderate threshold
        search_start = max(0, prev_pi + 1)
        search_end = min(n_pdf, next_pi)
        best_pi = -1
        best_score = 0.6

        for pi in range(search_start, search_end):
            if used_pdf[pi]:
                continue
            score = _text_similarity(r_text, pdf_blocks[pi].get('text', ''))
            if score > best_score:
                best_score = score
                best_pi = pi

        if best_pi >= 0:
            used_pdf[best_pi] = True
            matches[r_idx] = (best_pi, best_score, pdf_blocks[best_pi])

    # Build result
    result = []
    for r_idx, r_type, r_text in rendered:
        if r_idx not in matches:
            continue
        pdf_pi, score, block = matches[r_idx]
        elem_id = _compute_element_id(r_idx, r_type, r_text)
        result.append(UnifiedElement(
            element_id=elem_id,
            idx=r_idx,
            type=r_type,
            type_source='xml_matched',
            bbox={
                'page': block['page_num'],
                'x0': block['x0'],
                'y0': block['y0'],
                'x1': block['x1'],
                'y1': block['y1'],
            },
            text=block.get('text', ''),
            text_start=block.get('text', '')[:60],
            text_end=block.get('text', '')[-40:] if len(block.get('text', '')) > 40 else '',
            span=1,
            docx_para_idx=-1,
            match_confidence=score,
            font_info={
                'max_size': block.get('max_font_size', 12),
                'is_bold': block.get('is_bold', False),
                'is_italic': block.get('is_italic', False),
            },
        ))

    return result


def _fallback_from_pdf(pdf_pages: List[Dict]) -> List[UnifiedElement]:
    """Fallback: create elements directly from PDF blocks without XML matching."""
    result = []
    idx = 0
    for page in pdf_pages:
        for block in page['blocks']:
            text = block.get('text', '').strip()
            if not text:
                continue
            idx += 1
            elem_id = _compute_element_id(idx, 'para', text)
            result.append(UnifiedElement(
                element_id=elem_id,
                idx=idx,
                type='paragraph',
                type_source='pdf_fallback',
                bbox={
                    'page': page['page_num'],
                    'x0': block['x0'],
                    'y0': block['y0'],
                    'x1': block['x1'],
                    'y1': block['y1'],
                },
                text=text,
                text_start=text[:60],
                text_end=text[-40:] if len(text) > 40 else '',
                span=1,
                match_confidence=0.0,
                font_info={
                    'max_size': block.get('max_font_size', 12),
                    'is_bold': block.get('is_bold', False),
                    'is_italic': block.get('is_italic', False),
                },
            ))
    return result
