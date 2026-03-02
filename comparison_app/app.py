"""
Flask application for side-by-side comparison of source .docx files
and their generated S1000D XML data modules.
"""

import os
# Force UTF-8 as default encoding on Windows (prevents charmap codec errors)
os.environ.setdefault('PYTHONUTF8', '1')

import sys
import configparser

from flask import Flask, render_template, send_from_directory, send_file, abort, request, jsonify

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
from comparison_app.reference_store import get_reference, save_reference, init_reference_from_auto, delete_reference
from comparison_app.headless_comparator import extract_xml_elements, compare_elements, ElementInfo

app = Flask(__name__)

# Fix MIME types for ES modules (.mjs) — Windows registry often misses these
import mimetypes
mimetypes.add_type('application/javascript', '.mjs')
mimetypes.add_type('application/javascript', '.js')

# In-memory progress tracking for verification loops
_loop_progress = {}  # dmc_string -> {cycle, max_cycles, status}

# Read config
config = configparser.ConfigParser()
config.read(os.path.join(PROJECT_ROOT, 'config.ini'), encoding='utf-8')

INPUT_DIR = os.path.join(PROJECT_ROOT, config.get('processing', 'input_dir', fallback='doc_source'))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, config.get('processing', 'output_dir', fallback='./tg_web/suites/66935'))
GRAPHICS_DIR = os.path.join(OUTPUT_DIR, 'graphics')
ELEMENT_SOURCE = config.get('processing', 'element_source', fallback='docx_only')

# tg_web viewer config
TG_WEB_URL = config.get('tg_web', 'url', fallback='http://localhost:8082')
TG_WEB_SUITE_ID = config.get('tg_web', 'suite_id', fallback='66935')
TG_WEB_PM_CODE = config.get('tg_web', 'pm_code', fallback='S5-SFX44-ETP05-00')

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
    return render_template('index.html', pairs=pairs, word_available=_is_word_available(),
                           input_dir=INPUT_DIR, output_dir=OUTPUT_DIR,
                           tg_web_url=TG_WEB_URL, tg_web_suite_id=TG_WEB_SUITE_ID,
                           tg_web_pm_code=TG_WEB_PM_CODE)


@app.route('/api/config', methods=['GET'])
def get_config_api():
    """Return current configuration values."""
    return jsonify({
        'input_dir': INPUT_DIR,
        'output_dir': OUTPUT_DIR,
        'input_dir_raw': config.get('processing', 'input_dir', fallback='doc_source'),
        'output_dir_raw': config.get('processing', 'output_dir', fallback='./tg_web/suites/66935'),
        'tg_web_url': TG_WEB_URL,
        'tg_web_suite_id': TG_WEB_SUITE_ID,
        'tg_web_pm_code': TG_WEB_PM_CODE,
    }), 200


@app.route('/api/config', methods=['POST'])
def update_config_api():
    """Update config.ini values (preserves comments via regex replacement)."""
    import re as _re
    global INPUT_DIR, OUTPUT_DIR, GRAPHICS_DIR, TG_WEB_URL, TG_WEB_SUITE_ID, TG_WEB_PM_CODE

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    config_path = os.path.join(PROJECT_ROOT, 'config.ini')
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Regex-replace known keys (preserves comments and structure)
    replacements = {
        'input_dir': data.get('input_dir'),
        'output_dir': data.get('output_dir'),
        'url': data.get('tg_web_url'),
        'suite_id': data.get('tg_web_suite_id'),
        'pm_code': data.get('tg_web_pm_code'),
    }
    for key, value in replacements.items():
        if value is not None:
            content = _re.sub(
                rf'^({_re.escape(key)}\s*=\s*).*$',
                rf'\g<1>{value}',
                content, flags=_re.MULTILINE,
            )

    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(content)

    # Re-read config cleanly
    config.read(config_path, encoding='utf-8')
    INPUT_DIR = os.path.join(PROJECT_ROOT, config.get('processing', 'input_dir', fallback='doc_source'))
    OUTPUT_DIR = os.path.join(PROJECT_ROOT, config.get('processing', 'output_dir', fallback='./tg_web/suites/66935'))
    GRAPHICS_DIR = os.path.join(OUTPUT_DIR, 'graphics')
    TG_WEB_URL = config.get('tg_web', 'url', fallback='http://localhost:8082')
    TG_WEB_SUITE_ID = config.get('tg_web', 'suite_id', fallback='66935')
    TG_WEB_PM_CODE = config.get('tg_web', 'pm_code', fallback='S5-SFX44-ETP05-00')

    return jsonify({
        'status': 'ok',
        'input_dir': INPUT_DIR,
        'output_dir': OUTPUT_DIR,
    }), 200


@app.route('/api/reload-config', methods=['POST'])
def reload_config_api():
    """Re-read config.ini from disk and return fresh pairs list."""
    global INPUT_DIR, OUTPUT_DIR, GRAPHICS_DIR, ELEMENT_SOURCE
    global TG_WEB_URL, TG_WEB_SUITE_ID, TG_WEB_PM_CODE

    config_path = os.path.join(PROJECT_ROOT, 'config.ini')
    config.read(config_path, encoding='utf-8')

    INPUT_DIR = os.path.join(PROJECT_ROOT, config.get('processing', 'input_dir', fallback='doc_source'))
    OUTPUT_DIR = os.path.join(PROJECT_ROOT, config.get('processing', 'output_dir', fallback='./tg_web/suites/66935'))
    GRAPHICS_DIR = os.path.join(OUTPUT_DIR, 'graphics')
    ELEMENT_SOURCE = config.get('processing', 'element_source', fallback='docx_only')
    TG_WEB_URL = config.get('tg_web', 'url', fallback='http://localhost:8082')
    TG_WEB_SUITE_ID = config.get('tg_web', 'suite_id', fallback='66935')
    TG_WEB_PM_CODE = config.get('tg_web', 'pm_code', fallback='S5-SFX44-ETP05-00')

    pairs = get_comparison_pairs(INPUT_DIR, OUTPUT_DIR)
    return jsonify({
        'status': 'ok',
        'input_dir': INPUT_DIR,
        'output_dir': OUTPUT_DIR,
        'pairs': pairs,
    }), 200


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
                           element_source=ELEMENT_SOURCE,
                           errors=errors,
                           tg_web_url=TG_WEB_URL,
                           tg_web_suite_id=TG_WEB_SUITE_ID,
                           tg_web_pm_code=TG_WEB_PM_CODE)


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


@app.route('/api/pdf-blocks/<path:dmc_string>')
def get_pdf_blocks(dmc_string: str):
    """Return text blocks with bbox for each page of the PDF."""
    from comparison_app.pdf_block_extractor import extract_pdf_blocks

    pair = get_pair_by_dmc(dmc_string, INPUT_DIR, OUTPUT_DIR)
    if not pair or not pair['docx_exists']:
        abort(404)

    if not _is_word_available():
        abort(503, 'MS Word not available for PDF rendering')

    try:
        pdf_path = render_docx_to_pdf(pair['docx_path'], dmc_string)
        pages = extract_pdf_blocks(pdf_path)
        return jsonify(pages=pages)
    except Exception as e:
        abort(500, f'PDF block extraction failed: {e}')


@app.route('/api/hybrid-blocks/<path:dmc_string>')
def get_hybrid_blocks(dmc_string: str):
    """Return unified elements: PDF boundaries + DOCX types, matched by text."""
    from comparison_app.pdf_block_extractor import extract_pdf_blocks_full
    from docx import Document
    from parsers.elements_analyzer import analyze_document_elements
    from parsers.hybrid_matcher import match_pdf_to_docx

    pair = get_pair_by_dmc(dmc_string, INPUT_DIR, OUTPUT_DIR)
    if not pair or not pair['docx_exists']:
        abort(404)

    if not _is_word_available():
        abort(503, 'MS Word not available for PDF rendering')

    try:
        # Extract PDF blocks (full text, font metadata)
        pdf_path = render_docx_to_pdf(pair['docx_path'], dmc_string)
        pdf_pages = extract_pdf_blocks_full(pdf_path)

        # Extract DOCX elements (types, text)
        doc = Document(pair['docx_path'])
        docx_elements = analyze_document_elements(doc)

        # Match
        unified = match_pdf_to_docx(pdf_pages, docx_elements)

        return jsonify(
            element_source='hybrid',
            elements=[e.to_dict() for e in unified],
            pdf_pages=[{
                'page_num': p['page_num'],
                'width': p['width'],
                'height': p['height'],
            } for p in pdf_pages],
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        abort(500, f'Hybrid block extraction failed: {e}')


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


# ======================================================================
# Reference markup and verification API
# ======================================================================

@app.route('/api/reference/<path:dmc_string>', methods=['GET'])
def get_reference_api(dmc_string: str):
    """Get stored reference markup for a DMC."""
    ref = get_reference(dmc_string)
    if ref is None:
        return jsonify({'exists': False}), 200
    return jsonify({'exists': True, 'reference': ref}), 200


@app.route('/api/reference/<path:dmc_string>/init', methods=['POST'])
def init_reference_api(dmc_string: str):
    """Create initial reference from automatic docx element extraction."""
    pair = get_pair_by_dmc(dmc_string, INPUT_DIR, OUTPUT_DIR)
    if not pair or not pair['docx_exists']:
        return jsonify({'error': 'DOCX not found'}), 404

    try:
        xml_path = pair['xml_path'] if pair.get('xml_exists') else None
        ref = init_reference_from_auto(dmc_string, pair['docx_path'], xml_path=xml_path)
        return jsonify({'reference': ref}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reference/<path:dmc_string>', methods=['DELETE'])
def delete_reference_api(dmc_string: str):
    """Delete stored reference markup for a DMC."""
    deleted = delete_reference(dmc_string)
    return jsonify({'deleted': deleted}), 200


@app.route('/api/reference/<path:dmc_string>', methods=['POST'])
def save_reference_api(dmc_string: str):
    """Save user-edited reference markup."""
    data = request.get_json()
    if not data or 'elements' not in data:
        app.logger.warning('save_reference_api: missing elements in request for %s', dmc_string)
        return jsonify({'error': 'Missing elements'}), 400

    source = data.get('source', 'manual')
    app.logger.info('save_reference_api: saving %d elements for %s (source=%s)',
                     len(data['elements']), dmc_string, source)
    ref = save_reference(dmc_string, data['elements'], source=source)
    app.logger.info('save_reference_api: saved OK, %d elements returned', len(ref.get('elements', [])))
    return jsonify({'reference': ref}), 200


@app.route('/api/regenerate/<path:dmc_string>', methods=['POST'])
def regenerate_xml_api(dmc_string: str):
    """Re-run DOCX → XML conversion for a single document."""
    pair = get_pair_by_dmc(dmc_string, INPUT_DIR, OUTPUT_DIR)
    if not pair or not pair['docx_exists']:
        return jsonify({'error': 'DOCX not found'}), 404

    try:
        from main import get_llm_config
        from parsers.dmc_parser import (
            parse_dmc_from_folder_name, is_procedure_info_code,
            build_graphic_ident_prefix,
        )
        import configparser as _cp
        _cfg = _cp.ConfigParser()
        _cfg.read(os.path.join(PROJECT_ROOT, 'config.ini'), encoding='utf-8')
        llm_config = get_llm_config(_cfg)

        dmc_info = parse_dmc_from_folder_name(pair['folder_name'])
        if not dmc_info:
            return jsonify({'error': 'Cannot parse DMC from folder name'}), 400

        dm_code = dmc_info['dm_code']
        info_code = dm_code['infoCode']
        graphic_prefix = build_graphic_ident_prefix(dm_code)

        if is_procedure_info_code(info_code):
            from processing_scripts import procedure_processor
            procedure_processor.process_procedure_document(
                doc_path=pair['docx_path'],
                output_dir=OUTPUT_DIR,
                llm_config=llm_config,
                dm_code_override=dm_code,
                tech_name_override=dmc_info['tech_name'],
                info_name_override=dmc_info['info_name'],
                skip_pmc=True,
                graphic_ident_prefix=graphic_prefix,
            )
        else:
            from processing_scripts import descriptive_processor
            descriptive_processor.process_descriptive_document(
                doc_path=pair['docx_path'],
                output_dir=OUTPUT_DIR,
                llm_config=llm_config,
                dm_code_override=dm_code,
                tech_name_override=dmc_info['tech_name'],
                info_name_override=dmc_info['info_name'],
                skip_pmc=True,
                graphic_ident_prefix=graphic_prefix,
            )
        # After successful generation, regenerate PMC
        pmc_msg = ''
        try:
            pmc_path = _regenerate_pmc()
            pmc_msg = os.path.basename(pmc_path)
        except Exception as pmc_err:
            pmc_msg = f'PMC error: {pmc_err}'

        return jsonify({'status': 'ok', 'xml_path': pair['xml_path'], 'pmc': pmc_msg}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _regenerate_pmc() -> str:
    """Scan all DMC-*.xml in OUTPUT_DIR, extract dm_refs and illustrations,
    and regenerate the Publication Module (PMC) file."""
    import re as _re
    import glob as _glob
    from lxml import etree
    from generators.pm_generator import PMGenerator, create_pm_config

    dmc_files = sorted(_glob.glob(os.path.join(OUTPUT_DIR, 'DMC-*_ru-RU.xml')))
    if not dmc_files:
        raise ValueError('No DMC files found in output directory')

    parser = etree.XMLParser(resolve_entities=False, dtd_validation=False, load_dtd=False)
    all_dm_refs = []
    all_illustrations = {}
    model_code = None

    for dmc_file in dmc_files:
        try:
            tree = etree.parse(dmc_file, parser)
            root = tree.getroot()

            dm_code_elem = root.find('.//dmCode')
            if dm_code_elem is None:
                continue

            dm_code = dict(dm_code_elem.attrib)
            tech_name = root.findtext('.//dmTitle/techName', '')
            info_name = root.findtext('.//dmTitle/infoName', '')

            all_dm_refs.append({
                'dm_code': dm_code,
                'techName': tech_name,
                'infoName': info_name,
            })

            if model_code is None:
                model_code = dm_code.get('modelIdentCode', 'S5')

            # Collect illustration entities from DOCTYPE
            with open(dmc_file, 'r', encoding='utf-8') as f:
                raw = f.read(4096)  # DOCTYPE is always near the top
            doctype_m = _re.search(r'<!DOCTYPE\s+dmodule\s*\[(.*?)\]>', raw, _re.DOTALL)
            if doctype_m:
                for ent_name, ent_file in _re.findall(r'<!ENTITY\s+(\S+)\s+SYSTEM\s+"([^"]+)"', doctype_m.group(1)):
                    if ent_name != 'PUBLICATION_LOGO':
                        all_illustrations[ent_name] = ent_file
        except Exception:
            continue

    if not all_dm_refs:
        raise ValueError('No valid DM references extracted')

    pm_gen = PMGenerator(model_ident=model_code or 'S5')
    pm_cfg = create_pm_config(model_ident_code=model_code or 'S5', pm_title='Руководство')
    return pm_gen.generate_publication_module(pm_cfg, all_dm_refs, OUTPUT_DIR, all_illustrations)


@app.route('/api/verify/<path:dmc_string>', methods=['POST'])
def run_verification_api(dmc_string: str):
    """Run headless comparison between reference and current XML + XSD validation."""
    pair = get_pair_by_dmc(dmc_string, INPUT_DIR, OUTPUT_DIR)
    if not pair:
        return jsonify({'error': 'Pair not found'}), 404

    # Load reference
    ref = get_reference(dmc_string)
    if ref is None:
        return jsonify({'error': 'No reference markup saved'}), 400

    if not pair['xml_exists']:
        return jsonify({'error': 'XML not found'}), 404

    try:
        # Extract XML elements
        xml_elems = extract_xml_elements(pair['xml_path'])

        # Convert reference to ElementInfo
        ref_elems = [ElementInfo.from_dict(e) for e in ref['elements']
                     if e.get('type') != '_skip']

        # Compare
        report = compare_elements(ref_elems, xml_elems)

        # ── XSD validation ──
        xsd_valid = True
        xsd_element_issues = []
        try:
            from generators.s1000d_generator import S1000DGenerator
            from parsers.dmc_parser import is_procedure_info_code
            info_code = pair.get('info_code', '')
            schema = 'xsd/proced.xsd' if is_procedure_info_code(info_code) else 'xsd/descript.xsd'
            xsd_valid, xsd_structured = S1000DGenerator.validate_xml_with_details(
                pair['xml_path'], schema_file=schema)

            if not xsd_valid:
                from verify_loop import _map_xsd_to_source_elements
                from parsers.elements_analyzer import get_last_markup_result
                source_elements = get_last_markup_result(dmc_string)
                if source_elements:
                    xsd_element_issues = _map_xsd_to_source_elements(
                        xsd_structured, source_elements)
                else:
                    xsd_element_issues = [{
                        'source_idx': None, 'ref_idx': None,
                        'text_preview': (e.get('element_text') or '')[:50],
                        'user_type': None, 'original_type': None,
                        'xsd_error': e.get('message', ''),
                        'is_user_annotated': False,
                        'element_tag': e.get('element_tag'),
                        'xpath': e.get('xpath'),
                    } for e in xsd_structured]
        except Exception as xsd_err:
            xsd_valid = False
            xsd_element_issues = [{
                'source_idx': None, 'ref_idx': None,
                'text_preview': '', 'user_type': None,
                'original_type': None,
                'xsd_error': f'XSD validation error: {xsd_err}',
                'is_user_annotated': False,
                'element_tag': None, 'xpath': None,
            }]

        return jsonify({
            'report': report.to_dict(),
            'xsd_valid': xsd_valid,
            'xsd_element_issues': xsd_element_issues,
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/verify-loop/<path:dmc_string>', methods=['POST'])
def run_verify_loop_api(dmc_string: str):
    """Run the full verification loop (convert → compare → override → repeat)."""
    pair = get_pair_by_dmc(dmc_string, INPUT_DIR, OUTPUT_DIR)
    if not pair:
        return jsonify({'error': 'Pair not found'}), 404

    ref = get_reference(dmc_string)
    if ref is None:
        return jsonify({'error': 'No reference markup saved'}), 400

    if not pair['docx_exists']:
        return jsonify({'error': 'DOCX not found'}), 404

    # Read config for verification settings
    max_cycles = config.getint('verification', 'max_cycles', fallback=3)
    threshold = config.getfloat('verification', 'convergence_threshold', fallback=0.95)

    # Allow overrides from request body
    body = request.get_json(silent=True) or {}
    max_cycles = body.get('max_cycles', max_cycles)
    threshold = body.get('threshold', threshold)

    if max_cycles <= 0:
        return jsonify({'error': 'max_cycles must be > 0'}), 400

    llm_enabled = config.getboolean('llm', 'enabled', fallback=False)
    llm_config = {
        'enabled': llm_enabled,
        'ollama_url': config.get('llm', 'ollama_url', fallback='http://localhost:11434'),
        'ollama_model': config.get('llm', 'ollama_model', fallback='gemma3:4b-it-qat'),
        'batch_size': config.getint('llm', 'batch_size', fallback=20),
        'confidence_threshold': config.getfloat('llm', 'confidence_threshold', fallback=0.7),
        'cache_enabled': config.getboolean('llm', 'cache_enabled', fallback=True),
        'cache_dir': config.get('llm', 'cache_dir', fallback='.llm_cache'),
    }

    def progress_callback(cycle, total, status):
        _loop_progress[dmc_string] = {
            'cycle': cycle,
            'max_cycles': total,
            'status': status,
        }

    _loop_progress[dmc_string] = {'cycle': 0, 'max_cycles': max_cycles, 'status': 'starting'}

    try:
        from verify_loop import run_verification_loop
        results = run_verification_loop(
            dmc_string=dmc_string,
            input_dir=INPUT_DIR,
            output_dir=OUTPUT_DIR,
            max_cycles=max_cycles,
            threshold=threshold,
            llm_config=llm_config,
            progress_callback=progress_callback,
        )
        return jsonify({'results': results}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        _loop_progress.pop(dmc_string, None)


@app.route('/api/verify-loop-progress/<path:dmc_string>')
def verify_loop_progress(dmc_string: str):
    """Get current progress of verification loop."""
    progress = _loop_progress.get(dmc_string)
    if progress is None:
        return jsonify({'running': False}), 200
    return jsonify({'running': True, **progress}), 200


@app.route('/api/s1000d-html/<path:dmc_string>')
def get_s1000d_html(dmc_string: str):
    """Return fresh S1000D HTML for a DMC (used after verify loop completes)."""
    pair = get_pair_by_dmc(dmc_string, INPUT_DIR, OUTPUT_DIR)
    if not pair or not pair['xml_exists']:
        return jsonify({'error': 'XML not found'}), 404

    try:
        html = render_s1000d_to_html(pair['xml_path'])
        return jsonify({'html': html}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    import subprocess

    port = config.getint('comparison', 'port', fallback=5000)
    debug = config.getboolean('comparison', 'debug', fallback=True)

    # Start tg_web viewer server (if run_consoled.bat exists)
    tg_web_dir = os.path.join(PROJECT_ROOT, 'tg_web')
    tg_web_bat = os.path.join(tg_web_dir, 'run_consoled.bat')
    tg_web_proc = None
    if os.path.isfile(tg_web_bat):
        try:
            tg_web_proc = subprocess.Popen(
                ['cmd', '/c', 'run_consoled.bat'],
                cwd=tg_web_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f'tg_web server started (PID {tg_web_proc.pid})')
        except Exception as e:
            print(f'Warning: could not start tg_web: {e}')

    print(f'Comparison app starting on http://localhost:{port}')
    print(f'Input dir: {INPUT_DIR}')
    print(f'Output dir: {OUTPUT_DIR}')
    app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=False)

