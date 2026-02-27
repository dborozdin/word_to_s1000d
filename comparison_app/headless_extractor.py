"""
Element extraction from DOCX (via mammoth HTML) and S1000D XML files.

Data structures (ElementInfo, ComparisonReport) and all extraction/walking
logic live here.  Comparison logic remains in headless_comparator.py.
"""

import re
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
