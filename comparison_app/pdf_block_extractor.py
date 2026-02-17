"""Extract text blocks with bounding boxes from PDF using PyMuPDF.

Word-generated PDFs often store each visual line as a separate text object.
PyMuPDF faithfully reports these as individual blocks.  We post-process to:
  1. Detect and remove repeated page headers/footers.
  2. Merge adjacent lines into logical paragraphs/blocks using gap and
     indentation (x-position) analysis.
"""
import fitz  # pymupdf


def extract_pdf_blocks(pdf_path: str) -> list:
    """
    Returns per-page list of text blocks with bbox coordinates.
    Each page: {page_num, width, height, blocks: [{x0, y0, x1, y1, text, lines, max_font_size}, ...]}
    """
    doc = fitz.open(pdf_path)

    # First pass: extract raw line-level blocks from every page
    raw_pages = []
    for page in doc:
        rect = page.rect
        data = page.get_text("dict")
        blocks = []
        for block in data["blocks"]:
            if block["type"] != 0:  # 0 = text, 1 = image
                continue
            text = ""
            for line in block["lines"]:
                for span in line["spans"]:
                    text += span["text"]
                text += "\n"
            text = text.strip()
            if not text:
                continue
            bbox = block["bbox"]
            blocks.append({
                "x0": bbox[0], "y0": bbox[1],
                "x1": bbox[2], "y1": bbox[3],
                "text": text,
                "lines": len(block["lines"]),
                "max_font_size": max(
                    (span["size"] for line in block["lines"] for span in line["spans"]),
                    default=12
                ),
            })
        raw_pages.append({
            "page_num": page.number + 1,
            "width": rect.width,
            "height": rect.height,
            "blocks": blocks,
        })
    doc.close()

    # Detect repeated headers/footers across pages
    hf_zones = _detect_header_footer_zones(raw_pages)

    # Second pass: filter headers/footers, merge lines into logical blocks
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

    # Check bottom 15% zone
    bottom_cutoff = 100
    bottom_count = 0
    for rp in raw_pages:
        h = rp["height"]
        for b in rp["blocks"]:
            if b["y1"] > h * 0.85:
                bottom_count += 1
                break
    if bottom_count >= threshold:
        min_bottom_y0 = 100
        for rp in raw_pages:
            h = rp["height"]
            for b in rp["blocks"]:
                if b["y1"] > h * 0.85:
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


def _is_list_start(text: str) -> bool:
    """Check if text begins with a bullet/dash or numbered prefix."""
    t = text.strip()
    return bool(_BULLET_RE.match(t) or _NUMBERED_RE.match(t))


def _merge_lines_into_blocks(blocks: list) -> list:
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
    """
    if not blocks:
        return []

    blocks = sorted(blocks, key=lambda b: b["y0"])

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
    cur = _copy_block(blocks[0])
    cur_anchor_x0 = cur["x0"]  # x0 of the first line in this logical block

    for i in range(1, len(blocks)):
        b = blocks[i]
        gap = b["y0"] - cur["y1"]

        x_shift = b["x0"] - cur_anchor_x0
        # Rightward shift relative to the PREVIOUS line
        x_shift_prev = b["x0"] - blocks[i - 1]["x0"]

        # Decision: should we start a new block?
        new_block = False

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

        # 6. Bullet / numbered prefix at list indent → new list item
        if not new_block and _is_list_start(b["text"]):
            # Only split if this looks like a list indent (not body text)
            # i.e. x0 is more indented than the minimum x0 on this page
            new_block = True

        if new_block:
            merged.append(cur)
            cur = _copy_block(b)
            cur_anchor_x0 = cur["x0"]
        else:
            # Merge: extend current block
            cur["y1"] = max(cur["y1"], b["y1"])
            cur["x1"] = max(cur["x1"], b["x1"])
            cur["x0"] = min(cur["x0"], b["x0"])
            cur["lines"] += b["lines"]
            cur["text"] += " " + b["text"]
            cur["max_font_size"] = max(cur["max_font_size"], b["max_font_size"])

    merged.append(cur)
    return merged


def _copy_block(b: dict) -> dict:
    return {
        "x0": b["x0"], "y0": b["y0"],
        "x1": b["x1"], "y1": b["y1"],
        "text": b["text"],
        "lines": b["lines"],
        "max_font_size": b["max_font_size"],
    }
