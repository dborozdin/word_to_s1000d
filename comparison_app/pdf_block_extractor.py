"""Extract text blocks with bounding boxes from PDF using PyMuPDF.

Word-generated PDFs often store each visual line as a separate text object.
PyMuPDF faithfully reports these as individual blocks.  We post-process to:
  1. Detect and remove repeated page headers/footers.
  2. Merge adjacent lines into logical paragraphs/blocks using gap and
     indentation (x-position) analysis.
"""
import fitz  # pymupdf


def _rects_overlap(block: dict, table_bbox: tuple) -> bool:
    """Check if a text block overlaps with a table bounding box."""
    tx0, ty0, tx1, ty1 = table_bbox
    # Block centre must be inside the table rect (tolerant check)
    bx_mid = (block["x0"] + block["x1"]) / 2
    by_mid = (block["y0"] + block["y1"]) / 2
    return tx0 <= bx_mid <= tx1 and ty0 <= by_mid <= ty1


def _extract_raw_pages(pdf_path: str, full_mode: bool = False) -> list:
    """
    Extract raw line-level blocks from every page of a PDF.

    Args:
        pdf_path: Path to the PDF file.
        full_mode: If True, extract full text and font metadata (bold/italic).
                   If False, only text and max_font_size (original behaviour).
    """
    doc = fitz.open(pdf_path)
    raw_pages = []
    for page in doc:
        rect = page.rect
        data = page.get_text("dict")
        blocks = []
        for block in data["blocks"]:
            if block["type"] != 0:  # 0 = text, 1 = image
                continue
            text = ""
            total_chars = 0
            bold_chars = 0
            italic_chars = 0
            for line in block["lines"]:
                for span in line["spans"]:
                    span_text = span["text"]
                    text += span_text
                    if full_mode:
                        n = len(span_text)
                        total_chars += n
                        flags = span.get("flags", 0)
                        if flags & (1 << 4):  # bit 4 = bold
                            bold_chars += n
                        if flags & (1 << 1):  # bit 1 = italic
                            italic_chars += n
                text += "\n"
            text = text.strip()
            if not text:
                continue
            bbox = block["bbox"]
            entry = {
                "x0": bbox[0], "y0": bbox[1],
                "x1": bbox[2], "y1": bbox[3],
                "text": text,
                "lines": len(block["lines"]),
                "max_font_size": max(
                    (span["size"] for line in block["lines"] for span in line["spans"]),
                    default=12
                ),
            }
            if full_mode:
                entry["is_bold"] = (bold_chars > total_chars * 0.5) if total_chars else False
                entry["is_italic"] = (italic_chars > total_chars * 0.5) if total_chars else False
            blocks.append(entry)

        # Detect tables on this page using PyMuPDF's built-in table finder
        table_rects = []
        try:
            tables_result = page.find_tables()
            for t in tables_result.tables:
                table_rects.append(t.bbox)  # (x0, y0, x1, y1)
        except Exception:
            pass  # find_tables() may not be available in older PyMuPDF

        # Mark blocks that fall inside a table region
        for b in blocks:
            b["_in_table"] = False
            for tr in table_rects:
                if _rects_overlap(b, tr):
                    b["_in_table"] = True
                    break

        raw_pages.append({
            "page_num": page.number + 1,
            "width": rect.width,
            "height": rect.height,
            "blocks": blocks,
        })
    doc.close()
    return raw_pages


def extract_pdf_blocks(pdf_path: str) -> list:
    """
    Returns per-page list of text blocks with bbox coordinates.
    Each page: {page_num, width, height, blocks: [{x0, y0, x1, y1, text, lines, max_font_size}, ...]}
    Text is truncated to 80 chars for JSON transport.
    """
    raw_pages = _extract_raw_pages(pdf_path, full_mode=False)
    hf_zones = _detect_header_footer_zones(raw_pages)

    pages = []
    for rp in raw_pages:
        filtered = _filter_header_footer(rp["blocks"], rp["height"], hf_zones)
        merged = _merge_lines_into_blocks(filtered)
        # Truncate text for JSON transport
        for b in merged:
            b["text"] = b["text"][:80]
        pages.append({
            "page_num": rp["page_num"],
            "width": rp["width"],
            "height": rp["height"],
            "blocks": merged,
        })

    return pages


def extract_pdf_blocks_full(pdf_path: str) -> list:
    """
    Extended extraction: full text (no truncation), bold/italic metadata.
    Each block: {x0, y0, x1, y1, text, lines, max_font_size, is_bold, is_italic}
    """
    raw_pages = _extract_raw_pages(pdf_path, full_mode=True)
    hf_zones = _detect_header_footer_zones(raw_pages)

    pages = []
    for rp in raw_pages:
        filtered = _filter_header_footer(rp["blocks"], rp["height"], hf_zones)
        merged = _merge_lines_into_blocks(filtered, preserve_font_info=True)
        pages.append({
            "page_num": rp["page_num"],
            "width": rp["width"],
            "height": rp["height"],
            "blocks": merged,
        })

    return pages


# ---------------------------------------------------------------------------
# Header / footer detection
# ---------------------------------------------------------------------------

def _detect_header_footer_zones(raw_pages: list) -> dict:
    """
    Detect header/footer zones by finding y-ranges that contain text
    on most pages (>60%).  Returns {top_cutoff, bottom_cutoff} in
    percentage of page height.
    """
    if len(raw_pages) < 2:
        return {"top_cutoff": 0, "bottom_cutoff": 100}

    page_count = len(raw_pages)
    threshold = max(2, int(page_count * 0.6))

    # Check top 10% zone
    top_cutoff = 0
    top_count = 0
    for rp in raw_pages:
        h = rp["height"]
        for b in rp["blocks"]:
            if b["y0"] < h * 0.10:
                top_count += 1
                break
    if top_count >= threshold:
        max_top_y1 = 0
        for rp in raw_pages:
            h = rp["height"]
            for b in rp["blocks"]:
                if b["y0"] < h * 0.10:
                    pct = b["y1"] / h * 100
                    if pct > max_top_y1:
                        max_top_y1 = pct
        top_cutoff = max_top_y1 + 0.5

    # Check bottom 10% zone (narrower than before to avoid clipping content)
    bottom_cutoff = 100
    bottom_count = 0
    for rp in raw_pages:
        h = rp["height"]
        for b in rp["blocks"]:
            if b["y1"] > h * 0.90:
                bottom_count += 1
                break
    if bottom_count >= threshold:
        min_bottom_y0 = 100
        for rp in raw_pages:
            h = rp["height"]
            for b in rp["blocks"]:
                if b["y1"] > h * 0.90:
                    pct = b["y0"] / h * 100
                    if pct < min_bottom_y0:
                        min_bottom_y0 = pct
        bottom_cutoff = min_bottom_y0 - 0.5

    return {"top_cutoff": top_cutoff, "bottom_cutoff": bottom_cutoff}


def _filter_header_footer(blocks: list, page_height: float, hf_zones: dict) -> list:
    """Remove blocks falling within detected header/footer zones."""
    top = hf_zones["top_cutoff"]
    bottom = hf_zones["bottom_cutoff"]
    result = []
    for b in blocks:
        pct_y0 = b["y0"] / page_height * 100
        pct_y1 = b["y1"] / page_height * 100
        if pct_y1 <= top:
            continue
        if pct_y0 >= bottom:
            # Protect content-heavy blocks near page bottom from being filtered
            if len(b.get("text", "")) > 50:
                result.append(b)
            continue
        result.append(b)
    return result


# ---------------------------------------------------------------------------
# Line → block merging
# ---------------------------------------------------------------------------

import re

_BULLET_RE = re.compile(
    r'^[\-\u2013\u2014\u2212\u2022\u25CF\u25CB\u2023\u25AA\u25AB\u2043]'
)
_NUMBERED_RE = re.compile(r'^\d+[\.\)]\s')
# Multi-level section numbers: "3.1 ", "3.1.1 ", "3.2.4 " etc.
_SECTION_HDR_RE = re.compile(r'^\d+(?:\.\d+)+\s')
_TERMINAL_RE = re.compile(r'[.!?;][»"\'\)\]]*\s*$')


def _is_list_start(text: str) -> bool:
    """Check if text begins with a bullet/dash, numbered prefix, or section number."""
    t = text.strip()
    return bool(_BULLET_RE.match(t) or _NUMBERED_RE.match(t) or _SECTION_HDR_RE.match(t))


def _collapse_table_blocks(blocks: list, preserve_font_info: bool = False) -> list:
    """
    Collapse consecutive blocks marked _in_table into single composite blocks.
    Each group of table blocks becomes one block with is_table=True.
    Non-table blocks pass through unchanged.
    """
    result = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if not b.get("_in_table", False):
            result.append(b)
            i += 1
            continue
        # Start a table group
        group = [b]
        j = i + 1
        while j < len(blocks) and blocks[j].get("_in_table", False):
            group.append(blocks[j])
            j += 1
        # Merge group into one block
        merged = {
            "x0": min(g["x0"] for g in group),
            "y0": min(g["y0"] for g in group),
            "x1": max(g["x1"] for g in group),
            "y1": max(g["y1"] for g in group),
            "text": " | ".join(g["text"] for g in group),
            "lines": sum(g["lines"] for g in group),
            "max_font_size": max(g["max_font_size"] for g in group),
            "is_table": True,
        }
        if preserve_font_info:
            merged["is_bold"] = any(g.get("is_bold", False) for g in group)
            merged["is_italic"] = any(g.get("is_italic", False) for g in group)
        result.append(merged)
        i = j
    return result


def _merge_lines_into_blocks(blocks: list, preserve_font_info: bool = False) -> list:
    """
    Merge adjacent line-level blocks into logical text blocks.

    Word PDFs have almost uniform line spacing (~6.7 pts), so gap alone
    can't distinguish paragraph breaks.  Instead we combine:
      - **Gap criterion**: split when gap > min_gap × 1.6
      - **Indent criterion**: split when x0 shifts left (back-indent)
        or shifts right by more than ~font-size (new indent level).
        Small rightward shifts are treated as continuation/wrap lines.
      - **Bullet criterion**: lines starting with –/•/digit. always start
        a new block (even at the same indent level as previous).

    If preserve_font_info is True, is_bold/is_italic are propagated.
    """
    if not blocks:
        return []

    blocks = sorted(blocks, key=lambda b: b["y0"])

    # Collapse table blocks into single composite blocks before merging
    blocks = _collapse_table_blocks(blocks, preserve_font_info)

    # Compute median font size
    font_sizes = sorted(b["max_font_size"] for b in blocks)
    median_font = font_sizes[len(font_sizes) // 2] if font_sizes else 12

    # Compute the most common (modal) gap between consecutive blocks
    gaps = []
    for i in range(1, len(blocks)):
        g = blocks[i]["y0"] - blocks[i - 1]["y1"]
        if g > 0:
            gaps.append(g)

    if gaps:
        # Use the minimum positive gap as the baseline line spacing
        min_gap = min(gaps)
        gap_threshold = min_gap * 1.6
    else:
        gap_threshold = median_font * 1.3

    # Continuation tolerance: rightward shift up to this value = wrapped line
    continuation_tolerance = median_font * 1.1

    merged = []
    cur = _copy_block(blocks[0], preserve_font_info)
    cur_anchor_x0 = cur["x0"]  # x0 of the first line in this logical block

    for i in range(1, len(blocks)):
        b = blocks[i]
        gap = b["y0"] - cur["y1"]

        x_shift = b["x0"] - cur_anchor_x0
        # Rightward shift relative to the PREVIOUS line
        x_shift_prev = b["x0"] - blocks[i - 1]["x0"]

        # Decision: should we start a new block?
        new_block = False

        # 0. Table blocks are always standalone (already collapsed)
        if cur.get("is_table") or b.get("is_table"):
            new_block = True

        # 1. Large vertical gap → paragraph break
        if gap > gap_threshold:
            new_block = True

        # 2. Shift LEFT relative to anchor → return to outer indent / new block
        elif x_shift < -3:
            new_block = True

        # 3. Large rightward shift from anchor → new indent level
        elif x_shift > continuation_tolerance:
            new_block = True

        # 4. Return to anchor indent after continuation line → new list item
        elif (abs(x_shift) < 3 and
              abs(x_shift_prev) > 3 and x_shift_prev < 0):
            new_block = True

        # 5. Large font size change → heading boundary
        elif cur["max_font_size"] > 0:
            ratio = b["max_font_size"] / cur["max_font_size"]
            if ratio > 1.25 or ratio < 0.8:
                new_block = True

        # 6. Previous line ends with terminal punctuation at same indent
        #    → paragraph break (essential for prose text with uniform spacing)
        if not new_block and abs(x_shift) < 3:
            prev_text = blocks[i - 1]["text"].rstrip()
            if _TERMINAL_RE.search(prev_text):
                new_block = True

        # 7. Bullet / numbered prefix at list indent → new list item
        if not new_block and _is_list_start(b["text"]):
            # Only split if this looks like a list indent (not body text)
            # i.e. x0 is more indented than the minimum x0 on this page
            new_block = True

        if new_block:
            merged.append(cur)
            cur = _copy_block(b, preserve_font_info)
            cur_anchor_x0 = cur["x0"]
        else:
            # Merge: extend current block
            cur["y1"] = max(cur["y1"], b["y1"])
            cur["x1"] = max(cur["x1"], b["x1"])
            cur["x0"] = min(cur["x0"], b["x0"])
            cur["lines"] += b["lines"]
            cur["text"] += " " + b["text"]
            cur["max_font_size"] = max(cur["max_font_size"], b["max_font_size"])
            if preserve_font_info and "is_bold" in b:
                # Keep bold/italic if either part is bold/italic
                cur["is_bold"] = cur.get("is_bold", False) or b.get("is_bold", False)
                cur["is_italic"] = cur.get("is_italic", False) or b.get("is_italic", False)

    merged.append(cur)
    return merged


def _copy_block(b: dict, preserve_font_info: bool = False) -> dict:
    d = {
        "x0": b["x0"], "y0": b["y0"],
        "x1": b["x1"], "y1": b["y1"],
        "text": b["text"],
        "lines": b["lines"],
        "max_font_size": b["max_font_size"],
    }
    if b.get("is_table"):
        d["is_table"] = True
    if preserve_font_info:
        d["is_bold"] = b.get("is_bold", False)
        d["is_italic"] = b.get("is_italic", False)
    return d
