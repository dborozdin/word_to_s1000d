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
