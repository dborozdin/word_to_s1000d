"""
Flask application for side-by-side comparison of source .docx files
and their generated S1000D XML data modules.
"""

import os
import sys
import configparser

from flask import Flask, render_template, send_from_directory, send_file, abort, request

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from comparison_app.pair_resolver import get_comparison_pairs, get_pair_by_dmc
from comparison_app.docx_renderer import (
    render_docx_to_html,
    render_docx_to_pdf,
    render_docx_to_word_html,
    is_word_available,
    CACHE_DIR,
)
from comparison_app.s1000d_renderer import render_s1000d_to_html

app = Flask(__name__)

# Read config
config = configparser.ConfigParser()
config.read(os.path.join(PROJECT_ROOT, 'config.ini'), encoding='utf-8')

INPUT_DIR = os.path.join(PROJECT_ROOT, config.get('processing', 'input_dir', fallback='doc_source'))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, config.get('processing', 'output_dir', fallback='./tg_web/suites/66935'))
GRAPHICS_DIR = os.path.join(OUTPUT_DIR, 'graphics')

# Lazy MS Word availability check (avoids COM issues with Flask reloader)
_word_available_cache = None


def _is_word_available():
    global _word_available_cache
    if _word_available_cache is None:
        _word_available_cache = is_word_available()
    return _word_available_cache

# Valid render modes
MODES = ('pdf', 'wordhtml', 'html')


@app.route('/')
def index():
    """Module pair selector page."""
    pairs = get_comparison_pairs(INPUT_DIR, OUTPUT_DIR)
    return render_template('index.html', pairs=pairs, word_available=_is_word_available())


@app.route('/compare/<path:dmc_string>')
def compare(dmc_string: str):
    """Side-by-side comparison page for a specific DMC pair."""
    pair = get_pair_by_dmc(dmc_string, INPUT_DIR, OUTPUT_DIR)
    if not pair:
        abort(404)

    # Determine render mode
    word_ok = _is_word_available()
    render_mode = request.args.get('mode', 'pdf' if word_ok else 'html')
    if render_mode not in MODES:
        render_mode = 'pdf' if word_ok else 'html'
    if render_mode in ('pdf', 'wordhtml') and not word_ok:
        render_mode = 'html'

    docx_html = ''
    s1000d_html = ''
    errors = []

    # Left panel: docx rendering
    if pair['docx_exists']:
        if render_mode == 'html':
            try:
                docx_html = render_docx_to_html(pair['docx_path'])
            except Exception as e:
                errors.append(f'Ошибка рендеринга DOCX (mammoth): {e}')
        elif render_mode == 'wordhtml':
            try:
                docx_html, _ = render_docx_to_word_html(pair['docx_path'], dmc_string)
                docx_html = f'<div class="word-html-content">{docx_html}</div>'
            except Exception as e:
                errors.append(f'Ошибка рендеринга DOCX (Word HTML): {e}')
        # For PDF mode, the template uses pdf.js with /pdf/<dmc> endpoint
    else:
        errors.append('Исходный файл .docx не найден')

    # Right panel: S1000D rendering
    if pair['xml_exists']:
        try:
            s1000d_html = render_s1000d_to_html(pair['xml_path'])
        except Exception as e:
            errors.append(f'Ошибка рендеринга S1000D XML: {e}')
    else:
        errors.append('Сгенерированный XML файл не найден')

    return render_template('comparison.html',
                           pair=pair,
                           docx_html=docx_html,
                           s1000d_html=s1000d_html,
                           render_mode=render_mode,
                           word_available=word_ok,
                           errors=errors)


@app.route('/pdf/<path:dmc_string>')
def serve_pdf(dmc_string: str):
    """Generate (if needed) and serve PDF for a docx file."""
    pair = get_pair_by_dmc(dmc_string, INPUT_DIR, OUTPUT_DIR)
    if not pair or not pair['docx_exists']:
        abort(404)

    if not _is_word_available():
        abort(503, 'MS Word not available for PDF rendering')

    try:
        pdf_path = render_docx_to_pdf(pair['docx_path'], dmc_string)
        return send_file(pdf_path, mimetype='application/pdf')
    except Exception as e:
        abort(500, f'PDF generation failed: {e}')


@app.route('/wordhtml_res/<path:dmc_string>/<path:filename>')
def serve_word_html_resource(dmc_string: str, filename: str):
    """Serve images and other resources from Word HTML export."""
    resources_dir = os.path.join(CACHE_DIR, f'{dmc_string}_word.files')
    if not os.path.isdir(resources_dir):
        abort(404)
    return send_from_directory(resources_dir, filename)


@app.route('/graphics/<path:filename>')
def serve_graphic(filename):
    """Serve S1000D graphics from the suite graphics directory."""
    if not os.path.isdir(GRAPHICS_DIR):
        abort(404)
    return send_from_directory(GRAPHICS_DIR, filename)


if __name__ == '__main__':
    port = config.getint('comparison', 'port', fallback=5000)
    debug = config.getboolean('comparison', 'debug', fallback=True)
    print(f'Comparison app starting on http://localhost:{port}')
    print(f'Input dir: {INPUT_DIR}')
    print(f'Output dir: {OUTPUT_DIR}')
    print(f'MS Word available: {_is_word_available()}')
    app.run(host='0.0.0.0', port=port, debug=debug)
