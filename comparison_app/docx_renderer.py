"""
Converts .docx files to HTML (via mammoth or MS Word) or PDF (via MS Word COM).
Used for the left panel of the comparison view.
"""

import os
import re
import base64
import logging

import mammoth

logger = logging.getLogger(__name__)

# Cache directory (relative to this file)
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pdf_cache')


def _ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _is_cache_valid(cache_path: str, mtime_path: str, docx_mtime: str) -> bool:
    """Check if cached file is still valid based on source mtime."""
    if os.path.isfile(cache_path) and os.path.isfile(mtime_path):
        with open(mtime_path, 'r') as f:
            return f.read().strip() == docx_mtime
    return False


def _save_mtime(mtime_path: str, docx_mtime: str):
    with open(mtime_path, 'w') as f:
        f.write(docx_mtime)


def _word_com_convert(docx_path: str, output_path: str, file_format: int):
    """Convert docx via Word COM to a given format. Reusable for PDF and HTML."""
    import pythoncom
    import win32com.client

    docx_abs = os.path.abspath(docx_path)
    output_abs = os.path.abspath(output_path)

    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0

        doc = word.Documents.Open(docx_abs)
        # Force UTF-8 for HTML formats (10 = wdFormatFilteredHTML)
        if file_format in (8, 10):
            doc.WebOptions.Encoding = 65001  # msoEncodingUTF8
        doc.SaveAs2(output_abs, FileFormat=file_format)
        doc.Close(False)
    except Exception as e:
        raise RuntimeError(f'Word COM conversion failed (format={file_format}): {e}') from e
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


# ==========================================================================
# PDF rendering via MS Word COM
# ==========================================================================

def render_docx_to_pdf(docx_path: str, cache_key: str) -> str:
    """
    Convert a .docx file to PDF using MS Word COM automation.
    Returns path to the cached PDF file.
    """
    _ensure_cache_dir()

    pdf_path = os.path.join(CACHE_DIR, f'{cache_key}.pdf')
    mtime_path = os.path.join(CACHE_DIR, f'{cache_key}.pdf.mtime')
    docx_mtime = str(os.path.getmtime(docx_path))

    if _is_cache_valid(pdf_path, mtime_path, docx_mtime):
        return pdf_path

    _word_com_convert(docx_path, pdf_path, file_format=17)  # 17 = wdFormatPDF
    _save_mtime(mtime_path, docx_mtime)
    logger.info(f'PDF created: {os.path.basename(pdf_path)}')
    return pdf_path


# ==========================================================================
# Word filtered HTML rendering via MS Word COM
# ==========================================================================

def render_docx_to_word_html(docx_path: str, cache_key: str) -> tuple:
    """
    Convert a .docx file to filtered HTML using MS Word COM automation.

    Returns:
        (html_content, resources_dir) where:
        - html_content: str, the <body> content (no <html>/<head> wrappers)
        - resources_dir: str, path to directory with images used in the HTML
    """
    _ensure_cache_dir()

    html_path = os.path.join(CACHE_DIR, f'{cache_key}_word.html')
    mtime_path = os.path.join(CACHE_DIR, f'{cache_key}_word.mtime')
    docx_mtime = str(os.path.getmtime(docx_path))

    # Word creates a resources folder named <stem>.files/
    resources_dir = os.path.join(CACHE_DIR, f'{cache_key}_word.files')

    if not _is_cache_valid(html_path, mtime_path, docx_mtime):
        _word_com_convert(docx_path, html_path, file_format=10)  # 10 = wdFormatFilteredHTML
        _save_mtime(mtime_path, docx_mtime)
        logger.info(f'Word HTML created: {os.path.basename(html_path)}')

    # Read and extract body content
    with open(html_path, 'r', encoding='utf-8') as f:
        full_html = f.read()

    body_content = _extract_body(full_html)

    # Rewrite image paths to use our serving route
    body_content = re.sub(
        r'src="' + re.escape(f'{cache_key}_word.files/'),
        f'src="/wordhtml_res/{cache_key}/',
        body_content,
    )

    body_content = _annotate_html_blocks(body_content)
    return body_content, resources_dir


def _extract_body(html: str) -> str:
    """Extract content between <body> and </body> tags."""
    match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1)
    return html


# ==========================================================================
# Check Word availability
# ==========================================================================

def is_word_available() -> bool:
    """Check if MS Word COM automation is available."""
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            word = win32com.client.Dispatch("Word.Application")
            word.Quit()
            return True
        except Exception:
            return False
        finally:
            pythoncom.CoUninitialize()
    except ImportError:
        return False


# ==========================================================================
# HTML rendering via mammoth (fallback)
# ==========================================================================

MAMMOTH_STYLE_MAP = """
p[style-name='List Paragraph'] => ul > li:fresh
p[style-name='List Bullet'] => ul > li:fresh
p[style-name='List Bullet 2'] => ul > li:fresh
p[style-name='List Number'] => ol > li:fresh
p[style-name='List Number 2'] => ol > li:fresh
"""


def render_docx_to_html(docx_path: str) -> str:
    """Convert a .docx file to HTML using mammoth."""
    with open(docx_path, "rb") as docx_file:
        result = mammoth.convert_to_html(
            docx_file,
            convert_image=mammoth.images.img_element(_image_to_base64),
            style_map=MAMMOTH_STYLE_MAP,
        )

    html = result.value
    html = _convert_dash_lists(html)

    heading_counter = [0]

    def _add_heading_id(match):
        heading_counter[0] += 1
        tag = match.group(1)
        return f'<{tag} data-section-id="docx-sec-{heading_counter[0]}">'

    html = re.sub(r'<(h[1-6])>', _add_heading_id, html)
    html = _annotate_html_blocks(html)
    return f'<div class="docx-content">{html}</div>'


def _convert_dash_lists(html: str) -> str:
    """Convert consecutive <p> tags starting with dash characters into <ul>/<li>."""
    dash_pattern = re.compile(
        r'<p>([\-\u2013\u2014\u2212])\s*(.+?)</p>',
        re.DOTALL
    )

    parts = []
    in_list = False
    last_end = 0

    for match in dash_pattern.finditer(html):
        start = match.start()
        gap = html[last_end:start].strip()

        if not in_list:
            parts.append(html[last_end:start])
            parts.append('<ul class="dash-list">')
            in_list = True
        elif gap:
            parts.append('</ul>')
            parts.append(html[last_end:start])
            parts.append('<ul class="dash-list">')

        parts.append(f'<li>{match.group(2)}</li>')
        last_end = match.end()

    if in_list:
        parts.append('</ul>')

    parts.append(html[last_end:])
    return ''.join(parts)


def _image_to_base64(image):
    """Convert mammoth image to base64 data URI."""
    with image.open() as image_bytes:
        encoded = base64.b64encode(image_bytes.read()).decode("ascii")
    return {"src": f"data:{image.content_type};base64,{encoded}"}


# ==========================================================================
# Block-level annotation post-processing
# ==========================================================================

_BLOCK_TAG_MAP = {
    'h1': 'heading', 'h2': 'heading', 'h3': 'heading',
    'h4': 'heading', 'h5': 'heading', 'h6': 'heading',
    'p': 'para', 'ul': 'list', 'ol': 'list',
    'table': 'table', 'img': 'figure',
}

_BLOCK_PATTERN = re.compile(
    r'<(h[1-6]|p|ul|ol|table|img)(\s[^>]*>|>)',
    re.IGNORECASE,
)


def _annotate_html_blocks(html: str) -> str:
    """Add data-anno-idx and data-anno-type attributes to each block element."""
    counter = [0]

    def _replacer(match):
        tag = match.group(1).lower()
        anno_type = _BLOCK_TAG_MAP.get(tag, 'para')
        counter[0] += 1
        rest = match.group(2)
        return f'<{match.group(1)} data-anno-idx="{counter[0]}" data-anno-type="{anno_type}"{rest}'

    return _BLOCK_PATTERN.sub(_replacer, html)
