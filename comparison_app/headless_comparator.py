"""
Headless element extraction and comparison for docx and S1000D XML files.
Reuses rendering logic from docx_renderer and s1000d_renderer but returns
structured element lists instead of HTML.
"""

import re
import difflib
from dataclasses import dataclass, field, asdict
from typing import List, Tuple, Optional
from html.parser import HTMLParser

from lxml import etree


# ==========================================================================
# Data structures
# ==========================================================================

@dataclass
class ElementInfo:
    """A single annotated element from a document."""
    idx: int
    type: str
    text_start: str = ''
    text_end: str = ''
    span: int = 1
    stable_id: str = ''

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> 'ElementInfo':
        # Filter to known fields to tolerate extra keys
        known = {'idx', 'type', 'text_start', 'text_end', 'span', 'stable_id'}
        filtered = {k: v for k, v in d.items() if k in known}
        return ElementInfo(**filtered)


@dataclass
class ComparisonReport:
    """Result of comparing two element lists."""
    left_count: int = 0
    right_count: int = 0
    matched_pairs: List[Tuple[int, int]] = field(default_factory=list)
    left_unmatched: List[int] = field(default_factory=list)
    right_unmatched: List[int] = field(default_factory=list)
    type_mismatches: List[Tuple[int, int, str, str]] = field(default_factory=list)
    text_similarities: List[Tuple[int, int, float]] = field(default_factory=list)
    score: float = 0.0

    @property
    def is_converged(self) -> bool:
        return self.score >= 0.95

    def to_dict(self) -> dict:
        return asdict(self)


# ==========================================================================
# Extract elements from annotated HTML (docx via mammoth)
# ==========================================================================

class _AnnotatedHTMLParser(HTMLParser):
    """Parse HTML with data-anno-idx / data-anno-type attributes."""

    def __init__(self):
        super().__init__()
        self.elements: List[ElementInfo] = []
        self._current_idx: Optional[int] = None
        self._current_type: Optional[str] = None
        self._current_stable_id: str = ''
        self._current_text: list = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        anno_idx = attr_dict.get('data-anno-idx')
        if anno_idx is not None:
            # If we were collecting a previous element, finish it
            if self._current_idx is not None:
                self._finish_element()
            self._current_idx = int(anno_idx)
            self._current_type = attr_dict.get('data-anno-type', 'para')
            self._current_stable_id = attr_dict.get('data-element-id', '')
            self._current_text = []
            self._depth = 1
        elif self._current_idx is not None:
            self._depth += 1

    def handle_endtag(self, tag):
        if self._current_idx is not None:
            self._depth -= 1
            if self._depth <= 0:
                self._finish_element()

    def handle_data(self, data):
        if self._current_idx is not None:
            text = data.strip()
            if text:
                self._current_text.append(text)

    def _finish_element(self):
        full_text = ' '.join(self._current_text)
        self.elements.append(ElementInfo(
            idx=self._current_idx,
            type=self._current_type or 'para',
            text_start=full_text[:60],
            text_end=full_text[-40:] if len(full_text) > 40 else full_text,
            stable_id=self._current_stable_id,
        ))
        self._current_idx = None
        self._current_type = None
        self._current_stable_id = ''
        self._current_text = []
        self._depth = 0

    def close(self):
        if self._current_idx is not None:
            self._finish_element()
        super().close()


def extract_docx_elements(docx_path: str) -> List[ElementInfo]:
    """Extract structured element list from a .docx file via mammoth."""
    from comparison_app.docx_renderer import render_docx_to_html
    html = render_docx_to_html(docx_path)
    return _parse_annotated_html(html)


def _parse_annotated_html(html: str) -> List[ElementInfo]:
    """Parse HTML with data-anno-idx attributes into ElementInfo list."""
    parser = _AnnotatedHTMLParser()
    parser.feed(html)
    parser.close()
    # Sort by idx to ensure correct order
    parser.elements.sort(key=lambda e: e.idx)
    return parser.elements


# ==========================================================================
# Extract elements from S1000D XML
# ==========================================================================

def _local_tag(elem) -> str:
    """Get local name of an lxml element (strip namespace)."""
    tag = elem.tag
    if '}' in tag:
        return tag.split('}', 1)[1]
    return tag


def _text_content(elem) -> str:
    """Get all text content from an element and its children."""
    return ' '.join(elem.itertext()).strip()


def _text_snippet(elem) -> Tuple[str, str]:
    """Get first 60 and last 40 chars of element text."""
    text = _text_content(elem)
    text_start = text[:60]
    text_end = text[-40:] if len(text) > 40 else text
    return text_start, text_end


def extract_xml_elements(xml_path: str) -> List[ElementInfo]:
    """Extract structured element list from an S1000D XML file."""
    parser = etree.XMLParser(
        resolve_entities=False,
        dtd_validation=False,
        load_dtd=False,
    )
    tree = etree.parse(xml_path, parser)
    root = tree.getroot()

    elements = []
    counter = [0]

    def add_element(elem, anno_type: str):
        counter[0] += 1
        ts, te = _text_snippet(elem)
        elements.append(ElementInfo(
            idx=counter[0],
            type=anno_type,
            text_start=ts,
            text_end=te,
        ))

    # Note: dmTitle (techName + infoName) is S1000D metadata, not content.
    # It is always generated from the folder name, so comparing it against
    # user-annotated reference elements causes false mismatches.
    # Content-level headings come from <levelledPara><title> inside <description>.

    # Find content
    content = root.find('.//content')
    if content is None:
        return elements

    description = content.find('description')
    procedure = content.find('procedure')

    if description is not None:
        _walk_description(description, elements, counter, level=2)
    elif procedure is not None:
        _walk_procedure(procedure, elements, counter)

    return elements


def _walk_description(desc, elements, counter, level):
    """Walk <description> tree, collecting elements."""
    for child in desc:
        tag = _local_tag(child)
        if tag == 'levelledPara':
            _walk_levelled_para(child, elements, counter, level)


def _walk_levelled_para(lp, elements, counter, level):
    """Walk <levelledPara>, collecting elements."""
    has_title = False
    first_para = True
    for child in lp:
        tag = _local_tag(child)
        if tag == 'title':
            # <title> inside levelledPara → heading element
            text = _text_content(child)
            if text.strip():
                counter[0] += 1
                elements.append(ElementInfo(
                    idx=counter[0], type='heading',
                    text_start=text[:60],
                    text_end=text[-40:] if len(text) > 40 else text,
                ))
                has_title = True
                first_para = False
        elif tag == 'para':
            text = _text_content(child)
            if first_para and not has_title and level <= 4 and text.strip():
                # First para is often a heading (when no <title> present)
                has_list = child.find('.//randomList') is not None
                if not has_list:
                    counter[0] += 1
                    elements.append(ElementInfo(
                        idx=counter[0], type='heading',
                        text_start=text[:60],
                        text_end=text[-40:] if len(text) > 40 else text,
                    ))
                    first_para = False
                    continue
            _walk_para(child, elements, counter)
            first_para = False
        elif tag == 'table':
            counter[0] += 1
            ts, te = _text_snippet(child)
            elements.append(ElementInfo(idx=counter[0], type='table', text_start=ts, text_end=te))
            first_para = False
        elif tag == 'figure':
            counter[0] += 1
            title = child.findtext('.//title', '')
            elements.append(ElementInfo(idx=counter[0], type='figure', text_start=title[:60], text_end=title[-40:] if len(title) > 40 else title))
            first_para = False
        elif tag == 'levelledPara':
            _walk_levelled_para(child, elements, counter, level + 1)
            first_para = False
        elif tag == 'warning':
            counter[0] += 1
            ts, te = _text_snippet(child)
            elements.append(ElementInfo(idx=counter[0], type='warning', text_start=ts, text_end=te))
            first_para = False
        elif tag == 'caution':
            counter[0] += 1
            ts, te = _text_snippet(child)
            elements.append(ElementInfo(idx=counter[0], type='caution', text_start=ts, text_end=te))
            first_para = False
        elif tag == 'note':
            counter[0] += 1
            ts, te = _text_snippet(child)
            elements.append(ElementInfo(idx=counter[0], type='note', text_start=ts, text_end=te))
            first_para = False


def _walk_para(para_elem, elements, counter):
    """Walk a <para> element, handling nested lists."""
    # Check for nested lists
    has_random_list = para_elem.find('.//randomList') is not None
    has_seq_list = para_elem.find('.//sequentialList') is not None

    if has_random_list or has_seq_list:
        # Get para text before the list
        direct_text = ''
        for child in para_elem:
            tag = _local_tag(child)
            if tag in ('randomList', 'sequentialList'):
                break
            if child.text:
                direct_text += child.text
            if child.tail:
                direct_text += child.tail
        if para_elem.text:
            direct_text = para_elem.text + direct_text
        direct_text = direct_text.strip()

        if direct_text:
            counter[0] += 1
            elements.append(ElementInfo(
                idx=counter[0], type='para',
                text_start=direct_text[:60],
                text_end=direct_text[-40:] if len(direct_text) > 40 else direct_text,
            ))

        # Add lists
        for child in para_elem:
            tag = _local_tag(child)
            if tag == 'randomList':
                counter[0] += 1
                ts, te = _text_snippet(child)
                elements.append(ElementInfo(idx=counter[0], type='unnumbered_list', text_start=ts, text_end=te))
            elif tag == 'sequentialList':
                counter[0] += 1
                ts, te = _text_snippet(child)
                elements.append(ElementInfo(idx=counter[0], type='numbered_list', text_start=ts, text_end=te))
    else:
        # Simple para
        counter[0] += 1
        ts, te = _text_snippet(para_elem)
        elements.append(ElementInfo(idx=counter[0], type='para', text_start=ts, text_end=te))


def _walk_procedure(proc, elements, counter):
    """Walk <procedure> tree, collecting elements."""
    for child in proc:
        tag = _local_tag(child)
        if tag == 'preliminaryRqmts':
            counter[0] += 1
            elements.append(ElementInfo(idx=counter[0], type='heading',
                                       text_start='Предварительные требования', text_end='требования'))
            _walk_preliminary_rqmts(child, elements, counter)
        elif tag == 'mainProcedure':
            _walk_main_procedure(child, elements, counter)
        elif tag == 'closeRqmts':
            counter[0] += 1
            elements.append(ElementInfo(idx=counter[0], type='heading',
                                       text_start='Требования по завершении', text_end='завершении'))


def _walk_preliminary_rqmts(prelim, elements, counter):
    """Walk preliminary requirements."""
    for child in prelim:
        tag = _local_tag(child)
        if tag in ('reqSupportEquips', 'reqSupplies', 'reqSpares'):
            items = child.findall('.//' + tag.replace('req', '').rstrip('s').lower() + 'Descr')
            if not items:
                # Try alternate element names
                for desc_elem in child.iter():
                    dt = _local_tag(desc_elem)
                    if dt.endswith('Descr') and dt != tag:
                        items.append(desc_elem)
            if items:
                counter[0] += 1
                elements.append(ElementInfo(idx=counter[0], type='heading',
                                           text_start=tag, text_end=tag))
                counter[0] += 1
                elements.append(ElementInfo(idx=counter[0], type='table',
                                           text_start=f'{len(items)} items', text_end=''))
        elif tag == 'reqSafety':
            for safety_child in child:
                st = _local_tag(safety_child)
                if st == 'warning':
                    counter[0] += 1
                    ts, te = _text_snippet(safety_child)
                    elements.append(ElementInfo(idx=counter[0], type='warning', text_start=ts, text_end=te))
                elif st == 'caution':
                    counter[0] += 1
                    ts, te = _text_snippet(safety_child)
                    elements.append(ElementInfo(idx=counter[0], type='caution', text_start=ts, text_end=te))


def _walk_main_procedure(main_proc, elements, counter):
    """Walk main procedure steps."""
    counter[0] += 1
    elements.append(ElementInfo(idx=counter[0], type='heading',
                               text_start='Порядок выполнения работ', text_end='работ'))
    for child in main_proc:
        tag = _local_tag(child)
        if tag == 'proceduralStep':
            _walk_procedural_step(child, elements, counter)


def _walk_procedural_step(step, elements, counter):
    """Walk a single procedural step."""
    for child in step:
        tag = _local_tag(child)
        if tag == 'para':
            _walk_para(child, elements, counter)
        elif tag == 'table':
            counter[0] += 1
            ts, te = _text_snippet(child)
            elements.append(ElementInfo(idx=counter[0], type='table', text_start=ts, text_end=te))
        elif tag == 'figure':
            counter[0] += 1
            title = child.findtext('.//title', '')
            elements.append(ElementInfo(idx=counter[0], type='figure', text_start=title[:60], text_end=''))
        elif tag == 'warning':
            counter[0] += 1
            ts, te = _text_snippet(child)
            elements.append(ElementInfo(idx=counter[0], type='warning', text_start=ts, text_end=te))
        elif tag == 'caution':
            counter[0] += 1
            ts, te = _text_snippet(child)
            elements.append(ElementInfo(idx=counter[0], type='caution', text_start=ts, text_end=te))
        elif tag == 'note':
            counter[0] += 1
            ts, te = _text_snippet(child)
            elements.append(ElementInfo(idx=counter[0], type='note', text_start=ts, text_end=te))
        elif tag == 'proceduralStep':
            _walk_procedural_step(child, elements, counter)


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
    for li, elem in enumerate(left):
        if li in left_matched:
            continue
        l_text = (elem.text_start + ' ' + elem.text_end).strip()
        if not l_text:
            continue
        best_ri = None
        best_sim = 0.4  # minimum threshold
        for ri, r_elem in enumerate(right):
            if ri in right_matched:
                continue
            r_text = (r_elem.text_start + ' ' + r_elem.text_end).strip()
            if not r_text:
                continue
            sim = difflib.SequenceMatcher(None, l_text, r_text).ratio()
            if sim > best_sim:
                best_sim = sim
                best_ri = ri
        if best_ri is not None:
            left_matched[li] = best_ri
            right_matched[best_ri] = li

    # --- Phase 3: LCS fallback for remaining unmatched (by type) ---
    unmatched_left = [i for i in range(len(left)) if i not in left_matched]
    unmatched_right = [i for i in range(len(right)) if i not in right_matched]
    if unmatched_left and unmatched_right:
        ul_types = [left[i].type for i in unmatched_left]
        ur_types = [right[i].type for i in unmatched_right]
        lcs_l, lcs_r = _compute_lcs(ul_types, ur_types)
        for ul_pos, ur_pos in lcs_l.items():
            li = unmatched_left[ul_pos]
            ri = unmatched_right[ur_pos]
            left_matched[li] = ri
            right_matched[ri] = li

    # --- Build report ---
    for li, ri in sorted(left_matched.items()):
        report.matched_pairs.append((left[li].idx, right[ri].idx))

        # Track type mismatches
        if left[li].type != right[ri].type:
            report.type_mismatches.append((
                left[li].idx, right[ri].idx,
                left[li].type, right[ri].type
            ))

        # Text similarity
        l_text = left[li].text_start + left[li].text_end
        r_text = right[ri].text_start + right[ri].text_end
        if l_text and r_text:
            sim = difflib.SequenceMatcher(None, l_text, r_text).ratio()
            report.text_similarities.append((left[li].idx, right[ri].idx, round(sim, 3)))

    report.left_unmatched = [left[i].idx for i in range(len(left)) if i not in left_matched]
    report.right_unmatched = [right[i].idx for i in range(len(right)) if i not in right_matched]

    # --- Score: 40% match_ratio + 30% type_correctness + 30% text_similarity ---
    max_count = max(len(left), len(right))
    match_ratio = len(report.matched_pairs) / max_count if max_count > 0 else 0

    type_correct = sum(1 for li, ri in left_matched.items()
                       if left[li].type == right[ri].type)
    type_ratio = type_correct / len(left_matched) if left_matched else 0

    avg_text_sim = 0.0
    if report.text_similarities:
        avg_text_sim = sum(s for _, _, s in report.text_similarities) / len(report.text_similarities)

    report.score = round(0.4 * match_ratio + 0.3 * type_ratio + 0.3 * avg_text_sim, 3)

    return report
