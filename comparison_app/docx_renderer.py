"""
Converts .docx files to HTML using the mammoth library.
Used for the left panel of the comparison view.
"""

import mammoth
import base64
import re


def render_docx_to_html(docx_path: str) -> str:
    """
    Convert a .docx file to HTML.

    Images are embedded as base64 data URIs for self-contained HTML.
    Headings get sequential IDs for scroll sync anchoring.

    Returns: HTML string.
    """
    with open(docx_path, "rb") as docx_file:
        result = mammoth.convert_to_html(
            docx_file,
            convert_image=mammoth.images.img_element(_image_to_base64),
        )

    html = result.value

    # Add sequential IDs to headings for scroll sync
    heading_counter = [0]

    def _add_heading_id(match):
        heading_counter[0] += 1
        tag = match.group(1)
        return f'<{tag} data-section-id="docx-sec-{heading_counter[0]}">'

    html = re.sub(r'<(h[1-6])>', _add_heading_id, html)

    return f'<div class="docx-content">{html}</div>'


def _image_to_base64(image):
    """Convert mammoth image to base64 data URI."""
    with image.open() as image_bytes:
        encoded = base64.b64encode(image_bytes.read()).decode("ascii")
    return {"src": f"data:{image.content_type};base64,{encoded}"}
