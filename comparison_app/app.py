"""
Flask application for side-by-side comparison of source .docx files
and their generated S1000D XML data modules.
"""

import os
import sys
import configparser

from flask import Flask, render_template, send_from_directory, abort

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from comparison_app.pair_resolver import get_comparison_pairs, get_pair_by_dmc
from comparison_app.docx_renderer import render_docx_to_html
from comparison_app.s1000d_renderer import render_s1000d_to_html

app = Flask(__name__)

# Read config
config = configparser.ConfigParser()
config.read(os.path.join(PROJECT_ROOT, 'config.ini'), encoding='utf-8')

INPUT_DIR = os.path.join(PROJECT_ROOT, config.get('processing', 'input_dir', fallback='doc_source'))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, config.get('processing', 'output_dir', fallback='./tg_web/suites/66935'))
GRAPHICS_DIR = os.path.join(OUTPUT_DIR, 'graphics')


@app.route('/')
def index():
    """Module pair selector page."""
    pairs = get_comparison_pairs(INPUT_DIR, OUTPUT_DIR)
    return render_template('index.html', pairs=pairs)


@app.route('/compare/<path:dmc_string>')
def compare(dmc_string: str):
    """Side-by-side comparison page for a specific DMC pair."""
    pair = get_pair_by_dmc(dmc_string, INPUT_DIR, OUTPUT_DIR)
    if not pair:
        abort(404)

    docx_html = ''
    s1000d_html = ''
    errors = []

    if pair['docx_exists']:
        try:
            docx_html = render_docx_to_html(pair['docx_path'])
        except Exception as e:
            errors.append(f'Ошибка рендеринга DOCX: {e}')
    else:
        errors.append('Исходный файл .docx не найден')

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
                           errors=errors)


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
    app.run(host='0.0.0.0', port=port, debug=debug)
