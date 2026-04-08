"""
Flask application for side-by-side comparison of source .docx files
and their generated S1000D XML data modules.
"""

import os
# Force UTF-8 as default encoding on Windows (prevents charmap codec errors)
os.environ.setdefault('PYTHONUTF8', '1')

import sys
import configparser

# Add project root / internal root to path for imports
from app_paths import get_app_root, get_internal_root, get_config_path, get_xsd_path, long_path

PROJECT_ROOT = get_app_root()
_INTERNAL_ROOT = get_internal_root()
sys.path.insert(0, _INTERNAL_ROOT)

from flask import Flask, render_template, send_from_directory, send_file, abort, request, jsonify

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
from version import __version__ as APP_VERSION

app = Flask(__name__,
            template_folder=os.path.join(_INTERNAL_ROOT, 'comparison_app', 'templates'),
            static_folder=os.path.join(_INTERNAL_ROOT, 'comparison_app', 'static'))
app.jinja_env.globals['app_version'] = APP_VERSION

# Fix MIME types for ES modules (.mjs) — Windows registry often misses these
import mimetypes
mimetypes.add_type('application/javascript', '.mjs')
mimetypes.add_type('application/javascript', '.js')

# In-memory progress tracking for verification loops
_loop_progress = {}  # dmc_string -> {cycle, max_cycles, status}

# Global tg_web process handle (set in __main__, used by restart)
_tg_web_proc = None


def _get_tgweb_port() -> int:
    """Получить порт tg_web из config."""
    try:
        parsed = __import__('urllib.parse', fromlist=['urlparse']).urlparse(TG_WEB_URL)
        return parsed.port or 8082
    except Exception:
        return 8082


def _find_tgweb_pids(port: int) -> list:
    """Найти PID процессов tgwebserver.exe, слушающих заданный порт."""
    import subprocess
    pids = set()

    # 1) Найти PID, слушающие порт (netstat)
    listening_pids = set()
    try:
        out = subprocess.check_output(
            ['netstat', '-ano', '-p', 'TCP'],
            stderr=subprocess.DEVNULL, text=True
        )
        for line in out.splitlines():
            if f':{port}' in line and 'LISTENING' in line:
                parts = line.split()
                if parts:
                    try:
                        listening_pids.add(int(parts[-1]))
                    except ValueError:
                        pass
    except Exception:
        pass

    # 2) Найти PID процессов с именем tgwebserver.exe (tasklist)
    tgweb_pids = set()
    try:
        out = subprocess.check_output(
            ['tasklist', '/FI', 'IMAGENAME eq tgwebserver.exe', '/FO', 'CSV', '/NH'],
            stderr=subprocess.DEVNULL, text=True
        )
        for line in out.splitlines():
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2:
                try:
                    tgweb_pids.add(int(parts[1]))
                except ValueError:
                    pass
    except Exception:
        pass

    # Пересечение: tgwebserver.exe на нашем порту
    pids = tgweb_pids & listening_pids
    # Если порт не определился — возвращаем все tgwebserver.exe
    if not pids and tgweb_pids:
        pids = tgweb_pids

    return list(pids)


def _kill_tgweb_on_port(port: int):
    """Убить процессы tgwebserver.exe, слушающие заданный порт."""
    import subprocess
    pids = _find_tgweb_pids(port)
    for pid in pids:
        try:
            subprocess.run(
                ['taskkill', '/F', '/PID', str(pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


def _is_tgweb_running(port: int) -> bool:
    """Проверить, запущен ли tgwebserver.exe на заданном порту."""
    return len(_find_tgweb_pids(port)) > 0


def restart_tg_web():
    """Restart tg_web server via run_consoled.bat (читает ini, устанавливает пути).

    Всегда запускает в видимом консольном окне для отладки.
    """
    import subprocess
    global _tg_web_proc

    tg_web_dir = os.path.join(PROJECT_ROOT, 'tg_web')
    tg_web_bat = os.path.join(tg_web_dir, 'run_consoled.bat')
    if not os.path.isfile(tg_web_bat):
        return

    port = _get_tgweb_port()
    _kill_tgweb_on_port(port)

    _CREATE_NEW_CONSOLE = 0x00000010
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 4  # SW_SHOWNOACTIVATE — visible but not focused
        _tg_web_proc = subprocess.Popen(
            ['cmd', '/c', 'run_consoled.bat'],
            cwd=tg_web_dir,
            creationflags=_CREATE_NEW_CONSOLE,
            startupinfo=si,
        )
    except Exception:
        pass

# Read config
config = configparser.ConfigParser()
config.read(get_config_path(), encoding='utf-8')

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

# ── Verified flags (stored as JSON set of DMC strings) ──
_VERIFIED_FILE = os.path.join(OUTPUT_DIR, 'user_finetune', '_verified.json')


def _load_verified_set() -> set:
    try:
        import json
        with open(_VERIFIED_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    except (FileNotFoundError, ValueError):
        return set()


def _save_verified_set(verified: set):
    import json
    os.makedirs(os.path.dirname(_VERIFIED_FILE), exist_ok=True)
    with open(_VERIFIED_FILE, 'w', encoding='utf-8') as f:
        json.dump(sorted(verified), f, ensure_ascii=False, indent=2)


@app.route('/api/toggle-verified/<dmc_string>', methods=['POST'])
def api_toggle_verified(dmc_string):
    """Переключает флаг 'проверено' для данного DMC."""
    verified = _load_verified_set()
    if dmc_string in verified:
        verified.discard(dmc_string)
        state = False
    else:
        verified.add(dmc_string)
        state = True
    _save_verified_set(verified)
    return jsonify({'verified': state})


@app.route('/')
def index():
    """Module pair selector page."""
    pairs = get_comparison_pairs(INPUT_DIR, OUTPUT_DIR)
    structure_exists = len(pairs) > 0

    # Группируем pairs по подсистемам для иерархического отображения
    subsystem_groups = []
    if pairs and pairs[0].get('subsystem_group'):
        from collections import OrderedDict
        groups = OrderedDict()
        for pair in pairs:
            key = pair.get('subsystem_group', '')
            if key not in groups:
                groups[key] = {
                    'name': pair.get('subsystem_name', key),
                    'group_key': key,
                    'pairs': []
                }
            groups[key]['pairs'].append(pair)
        subsystem_groups = list(groups.values())

    # Прогресс-данные
    total_pairs = len(pairs)
    docx_ready = sum(1 for p in pairs if p['docx_exists'])
    xml_ready = sum(1 for p in pairs if p['xml_exists'])
    verified_set = _load_verified_set()
    for p in pairs:
        p['verified'] = p['dmc_string'] in verified_set
    verified_count = sum(1 for p in pairs if p['verified'])

    # Per-group статистика
    if subsystem_groups:
        for g in subsystem_groups:
            g['xml_ready'] = sum(1 for p in g['pairs'] if p['xml_exists'])
            g['verified'] = sum(1 for p in g['pairs'] if p['verified'])

    raw_input_dir = config.get('raw_import', 'raw_input_dir', fallback='')
    reference_dir = config.get('raw_import', 'reference_dir', fallback='')

    input_dir_raw = config.get('processing', 'input_dir', fallback='doc_source')
    output_dir_raw = config.get('processing', 'output_dir', fallback='./tg_web/suites/66935')

    return render_template('index.html', pairs=pairs, word_available=_is_word_available(),
                           input_dir=input_dir_raw, output_dir=output_dir_raw,
                           tg_web_url=TG_WEB_URL, tg_web_suite_id=TG_WEB_SUITE_ID,
                           tg_web_pm_code=TG_WEB_PM_CODE,
                           subsystem_groups=subsystem_groups,
                           raw_input_dir=raw_input_dir,
                           reference_dir=reference_dir,
                           structure_exists=structure_exists,
                           total_pairs=total_pairs,
                           docx_ready=docx_ready,
                           xml_ready=xml_ready,
                           verified_count=verified_count)


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
        'raw_input_dir': config.get('raw_import', 'raw_input_dir', fallback=''),
        'reference_dir': config.get('raw_import', 'reference_dir', fallback=''),
    }), 200


@app.route('/api/config', methods=['POST'])
def update_config_api():
    """Update config.ini values (preserves comments via regex replacement)."""
    import re as _re
    global INPUT_DIR, OUTPUT_DIR, GRAPHICS_DIR, TG_WEB_URL, TG_WEB_SUITE_ID, TG_WEB_PM_CODE

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    _cfg_path = get_config_path()
    with open(_cfg_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Regex-replace known keys (preserves comments and structure)
    replacements = {
        'input_dir': data.get('input_dir'),
        'output_dir': data.get('output_dir'),
        'raw_input_dir': data.get('raw_input_dir'),
        'reference_dir': data.get('reference_dir'),
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

    with open(_cfg_path, 'w', encoding='utf-8') as f:
        f.write(content)

    # Re-read config cleanly
    config.read(_cfg_path, encoding='utf-8')
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

    config.read(get_config_path(), encoding='utf-8')

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

    verified_set = _load_verified_set()
    is_verified = dmc_string in verified_set

    return render_template('comparison.html',
                           pair=pair,
                           docx_html=docx_html,
                           s1000d_html=s1000d_html,
                           render_mode=render_mode,
                           word_available=word_ok,
                           element_source=ELEMENT_SOURCE,
                           errors=errors,
                           verified=is_verified,
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
        # Используем docx_path, а если нет — конвертируем .doc в .docx сначала
        doc_file = pair['docx_path']
        if doc_file is None and pair.get('doc_path'):
            from parsers.doc_converter import convert_doc_to_docx_batch
            src = pair['doc_path']
            dst = os.path.splitext(src)[0] + '.docx'
            if not os.path.isfile(long_path(dst)):
                results = convert_doc_to_docx_batch([(src, dst)])
                if not results or not results[0][1]:
                    abort(500, f'Не удалось конвертировать .doc: {src}')
            doc_file = dst
        if doc_file is None:
            abort(404, 'Нет .docx/.doc файла')
        pdf_path = render_docx_to_pdf(doc_file, dmc_string)
        return send_file(pdf_path, mimetype='application/pdf')
    except Exception as e:
        app.logger.error(f'PDF generation failed for {dmc_string}: {e}', exc_info=True)
        # Retry once after 1 sec (Word COM race condition)
        import time
        time.sleep(1)
        try:
            pdf_path = render_docx_to_pdf(doc_file, dmc_string)
            return send_file(pdf_path, mimetype='application/pdf')
        except Exception as e2:
            app.logger.error(f'PDF retry also failed for {dmc_string}: {e2}')
            abort(500, f'PDF generation failed: {e2}')


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
        doc_file = pair.get('docx_path') or pair.get('doc_path')
        pdf_path = render_docx_to_pdf(doc_file, dmc_string)
        is_procedural = int(pair.get('info_code', '0')) >= 100
        pages = extract_pdf_blocks(pdf_path, collapse_tables=not is_procedural)
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
        doc_file = pair.get('docx_path') or pair.get('doc_path')
        pdf_path = render_docx_to_pdf(doc_file, dmc_string)
        is_procedural = int(pair.get('info_code', '0')) >= 100

        # Extract PDF blocks (full text, font metadata)
        pdf_pages = extract_pdf_blocks_full(pdf_path, collapse_tables=not is_procedural)

        if is_procedural and pair.get('xml_exists'):
            # Процедурные МД: match PDF blocks → XML elements напрямую
            from comparison_app.procedural_pdf_matcher import match_pdf_to_xml
            unified = match_pdf_to_xml(pdf_pages, pair['xml_path'])
        else:
            # Описательные МД: стандартный path через DOCX matching
            docx_path = pair.get('docx_path') or pair.get('doc_path')
            doc = Document(docx_path)
            docx_elements = analyze_document_elements(doc)
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
    """Get stored reference markup for a DMC.

    Если reference создан не из XML (auto_hybrid/auto), а XML уже существует —
    автоматически пересоздаёт reference из XML для лучшего соответствия панелей.
    """
    ref = get_reference(dmc_string)
    if ref is None:
        return jsonify({'exists': False}), 200

    # Auto-upgrade: если reference создан автоматически (не вручную отредактирован)
    # и не из XML, а XML уже есть — пересоздать для лучшего соответствия
    source = ref.get('source', '')
    if source in ('auto', 'auto_hybrid') and 'xml_derived' not in source:
        pair = get_pair_by_dmc(dmc_string, INPUT_DIR, OUTPUT_DIR)
        if pair and pair.get('xml_exists'):
            try:
                docx_path = pair.get('docx_path') or pair.get('doc_path')
                if docx_path:
                    ref = init_reference_from_auto(dmc_string, docx_path, xml_path=pair['xml_path'])
            except Exception:
                pass  # fallback to existing reference

    return jsonify({'exists': True, 'reference': ref}), 200


@app.route('/api/reference/<path:dmc_string>/init', methods=['POST'])
def init_reference_api(dmc_string: str):
    """Create initial reference from automatic docx element extraction."""
    pair = get_pair_by_dmc(dmc_string, INPUT_DIR, OUTPUT_DIR)
    if not pair or not pair['docx_exists']:
        return jsonify({'error': 'DOCX not found'}), 404

    try:
        docx_path = pair.get('docx_path') or pair.get('doc_path')
        xml_path = pair['xml_path'] if pair.get('xml_exists') else None
        ref = init_reference_from_auto(dmc_string, docx_path, xml_path=xml_path)
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
        _cfg.read(get_config_path(), encoding='utf-8')
        llm_config = get_llm_config(_cfg)

        dmc_info = parse_dmc_from_folder_name(pair['folder_name'])
        if not dmc_info:
            return jsonify({'error': 'Cannot parse DMC from folder name'}), 400

        dm_code = dmc_info['dm_code']
        info_code = dm_code['infoCode']
        graphic_prefix = build_graphic_ident_prefix(dm_code)

        # Определяем путь к документу (docx или doc с конвертацией)
        doc_path = pair['docx_path']
        if doc_path is None and pair.get('doc_path'):
            # .doc файл — нужна конвертация в .docx
            from parsers.doc_converter import convert_doc_to_docx_batch
            src = pair['doc_path']
            dst = os.path.splitext(src)[0] + '.docx'
            if not os.path.isfile(long_path(dst)):
                results = convert_doc_to_docx_batch([(src, dst)])
                if not results or not results[0][1]:
                    return jsonify({'error': f'Не удалось конвертировать .doc в .docx: {src}'}), 500
            doc_path = dst

        if doc_path is None:
            return jsonify({'error': 'Нет .docx/.doc файла'}), 404

        if is_procedure_info_code(info_code):
            from processing_scripts import procedure_processor
            procedure_processor.process_procedure_document(
                doc_path=doc_path,
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
                doc_path=doc_path,
                output_dir=OUTPUT_DIR,
                llm_config=llm_config,
                dm_code_override=dm_code,
                tech_name_override=dmc_info['tech_name'],
                info_name_override=dmc_info['info_name'],
                skip_pmc=True,
                graphic_ident_prefix=graphic_prefix,
            )
        return jsonify({'status': 'ok', 'xml_path': pair['xml_path']}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/raw-stats')
def api_raw_stats():
    """Статистика по сырым исходным документам."""
    import sys as _sys
    _sys.path.insert(0, PROJECT_ROOT)
    raw_dir = config.get('raw_import', 'raw_input_dir', fallback='')
    if not raw_dir:
        return jsonify({'available': False})
    raw_abs = os.path.join(PROJECT_ROOT, raw_dir) if not os.path.isabs(raw_dir) else raw_dir
    if not os.path.isdir(raw_abs):
        return jsonify({'available': False, 'path': raw_dir})
    from raw_to_structured import scan_raw_folder
    docs = scan_raw_folder(raw_abs)
    return jsonify({
        'available': True,
        'path': raw_dir,
        'total': len(docs),
        'descriptions': sum(1 for d in docs if d.doc_type == 'description'),
        'tk': sum(1 for d in docs if d.doc_type == 'tk'),
        'special': sum(1 for d in docs if d.doc_type in ('piun', 'tk_to', 'special')),
        'graphics': sum(1 for d in docs if d.doc_type == 'graphic'),
    })


@app.route('/api/generate-structure', methods=['POST'])
def api_generate_structure():
    """Запуск raw_to_structured.py: генерация структуры папок с DMC-кодами."""
    import sys as _sys
    _sys.path.insert(0, PROJECT_ROOT)
    from raw_to_structured import (scan_raw_folder, build_data_modules,
                                    create_folder_structure, validate_against_reference)

    data = request.get_json() or {}
    raw_input = data.get('raw_input_dir',
                         config.get('raw_import', 'raw_input_dir', fallback=''))
    reference = data.get('reference_dir',
                         config.get('raw_import', 'reference_dir', fallback=''))

    if not raw_input:
        return jsonify({'error': 'raw_input_dir не задан'}), 400

    raw_input_abs = os.path.join(PROJECT_ROOT, raw_input) if not os.path.isabs(raw_input) else raw_input
    if not os.path.isdir(raw_input_abs):
        return jsonify({'error': f'Папка не найдена: {raw_input}'}), 400

    output_abs = INPUT_DIR  # результат пишется в input_dir текущего pipeline

    try:
        # Очистка выходной папки перед генерацией
        import shutil
        if os.path.isdir(output_abs):
            shutil.rmtree(output_abs)

        docs = scan_raw_folder(raw_input_abs)
        components = build_data_modules(docs)
        created = create_folder_structure(components, output_abs)

        result = {
            'status': 'ok',
            'components': len(components),
            'data_modules': sum(len(c.data_modules) for c in components),
            'files_copied': len(created),
        }

        # Валидация (если задан reference)
        if reference:
            ref_abs = os.path.join(PROJECT_ROOT, reference) if not os.path.isabs(reference) else reference
            if os.path.isdir(ref_abs):
                result['validation'] = validate_against_reference(output_abs, ref_abs, silent=True)

        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/restart-tgweb', methods=['POST'])
def restart_tgweb_api():
    """Restart tg_web server to re-index suites."""
    try:
        restart_tg_web()
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/regenerate-pmc', methods=['POST'])
def regenerate_pmc_api():
    """Принудительно пересоздать PMC из всех XML в output_dir."""
    try:
        pmc_path = _regenerate_pmc()
        return jsonify({'status': 'ok', 'pmc': os.path.basename(pmc_path)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/ensure-tgweb', methods=['POST'])
def ensure_tgweb_api():
    """Проверить, запущен ли tg_web. Если нет — запустить."""
    port = _get_tgweb_port()
    if _is_tgweb_running(port):
        return jsonify({'status': 'already_running'}), 200
    try:
        restart_tg_web()
        return jsonify({'status': 'started'}), 200
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

    # Тегируем dm_refs подсистемами для иерархического PMC
    from comparison_app.pair_resolver import get_comparison_pairs
    pairs = get_comparison_pairs(INPUT_DIR, OUTPUT_DIR)
    dmc_to_subsystem = {}
    for pair in pairs:
        if pair.get('subsystem_group'):
            dmc_to_subsystem[pair['dmc_string']] = {
                'group': pair['subsystem_group'],
                'name': pair.get('subsystem_name', '')
            }
    if dmc_to_subsystem:
        from parsers.dmc_parser import dm_code_to_string as _dmc_str
        for ref in all_dm_refs:
            dmc_str = _dmc_str(ref['dm_code'])
            info = dmc_to_subsystem.get(dmc_str)
            if info:
                ref['_subsystem_group'] = info['group']
                ref['_subsystem_name'] = info['name']

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
            schema = get_xsd_path('proced.xsd') if is_procedure_info_code(info_code) else get_xsd_path('descript.xsd')
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
    import socket
    import subprocess
    from urllib.parse import urlparse

    port = config.getint('comparison', 'port', fallback=5000)
    debug = config.getboolean('comparison', 'debug', fallback=True)

    # Start tg_web viewer server (if not already running on its port)
    tg_web_dir = os.path.join(PROJECT_ROOT, 'tg_web')
    tg_web_bat = os.path.join(tg_web_dir, 'run_consoled.bat')

    _parsed_tg = urlparse(TG_WEB_URL)
    _tg_host = _parsed_tg.hostname or 'localhost'
    _tg_port = _parsed_tg.port or 8082

    def _is_port_in_use(host: str, p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex((host, p)) == 0

    # Убить оставшиеся tgwebserver.exe на нашем порту (сироты от предыдущих запусков)
    _kill_tgweb_on_port(_tg_port)
    import time; time.sleep(0.5)

    if _is_port_in_use(_tg_host, _tg_port):
        print(f'tg_web port {_tg_port} still in use (external process?)')
    else:
        restart_tg_web()
        if _tg_web_proc:
            print(f'tg_web server started (PID {_tg_web_proc.pid})')

    print(f'Word to S1000D v{APP_VERSION}')
    print(f'Comparison app starting on http://localhost:{port}')
    print(f'Input dir: {INPUT_DIR}')
    print(f'Output dir: {OUTPUT_DIR}')
    app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=False)

