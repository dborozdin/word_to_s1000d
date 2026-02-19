"""
Verification loop orchestrator.
Single-pass system: apply user reference markup → generate XML → compare → XSD validate.
Reports XSD issues mapped to source elements (user-annotated vs auto-classified).
Can be invoked as CLI or imported by the Flask app.
"""

import os
import sys
import json
import configparser
from typing import Dict, List, Optional

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from comparison_app.headless_comparator import (
    extract_xml_elements,
    compare_elements,
    ElementInfo,
    ComparisonReport,
)
from comparison_app.reference_store import get_reference
from comparison_app.pair_resolver import get_pair_by_dmc


# ======================================================================
# Overrides I/O (kept for backward compat, clear on each run)
# ======================================================================

OVERRIDES_DIR = os.path.join(PROJECT_ROOT, 'comparison_app', '_overrides')


def _overrides_path(dmc_string: str) -> str:
    return os.path.join(OVERRIDES_DIR, f'{dmc_string}.json')


def clear_overrides(dmc_string: str):
    """Remove overrides file for a DMC."""
    path = _overrides_path(dmc_string)
    if os.path.isfile(path):
        os.remove(path)


# ======================================================================
# XSD error → source element mapping
# ======================================================================

def _map_xsd_to_source_elements(
    xsd_errors: List[dict],
    source_elements: List[dict],
) -> List[dict]:
    """Map XSD validation errors to source elements via text matching.

    For each XSD error, finds the source element whose content matches
    the error's element_text and reports whether it was user-annotated.
    """
    mapped = []
    for error in xsd_errors:
        error_text = (error.get('element_text') or '').strip()
        source_idx = None
        is_user = False
        user_type = None
        original_type = None
        ref_idx = None

        # Find source element by text prefix match
        if error_text:
            for i, elem in enumerate(source_elements):
                content_start = elem.get('content', '')[:60].strip()
                if not content_start:
                    continue
                prefix = min(20, len(error_text), len(content_start))
                if prefix >= 3 and error_text[:prefix] == content_start[:prefix]:
                    source_idx = i
                    is_user = elem.get('_ref_annotated', False)
                    user_type = elem.get('_ref_type_raw')
                    original_type = elem.get('_original_type')
                    ref_idx = elem.get('_ref_idx')
                    break

        mapped.append({
            'source_idx': source_idx,
            'ref_idx': ref_idx,
            'text_preview': error_text[:50] if error_text else '',
            'user_type': user_type,
            'original_type': original_type,
            'xsd_error': error.get('message', ''),
            'is_user_annotated': is_user,
            'element_tag': error.get('element_tag'),
            'xpath': error.get('xpath'),
        })
    return mapped


# ======================================================================
# Single conversion run
# ======================================================================

def _run_conversion(docx_path: str, output_dir: str, dmc_string: str,
                    llm_config: Dict = None, dm_code: Dict = None,
                    tech_name: str = None, info_name: str = None,
                    graphic_prefix: str = None, module_type: str = 'descriptive'):
    """Run one conversion cycle for a single document."""
    if module_type == 'procedure':
        from processing_scripts.procedure_processor import process_procedure_document
        process_procedure_document(
            doc_path=docx_path,
            output_dir=output_dir,
            llm_config=llm_config,
            dm_code_override=dm_code,
            tech_name_override=tech_name,
            info_name_override=info_name,
            skip_pmc=True,
            graphic_ident_prefix=graphic_prefix,
        )
    else:
        from processing_scripts.descriptive_processor import process_descriptive_document
        process_descriptive_document(
            doc_path=docx_path,
            output_dir=output_dir,
            llm_config=llm_config,
            dm_code_override=dm_code,
            tech_name_override=tech_name,
            info_name_override=info_name,
            skip_pmc=True,
            graphic_ident_prefix=graphic_prefix,
        )


def _find_xml_for_dmc(output_dir: str, dmc_string: str) -> Optional[str]:
    """Find the generated XML file for a DMC string in the output directory."""
    expected = f'{dmc_string}_ru-RU.xml'
    path = os.path.join(output_dir, expected)
    if os.path.isfile(path):
        return path
    # Fallback: search for partial match
    for fname in os.listdir(output_dir):
        if fname.endswith('.xml') and dmc_string in fname:
            return os.path.join(output_dir, fname)
    return None


# ======================================================================
# Main verification loop (single pass)
# ======================================================================

def run_verification_loop(
    dmc_string: str,
    input_dir: str,
    output_dir: str,
    max_cycles: int = 3,
    threshold: float = 0.95,
    llm_config: Dict = None,
    progress_callback=None,
) -> List[dict]:
    """
    Single-pass verification for a single DMC.

    1. Clear overrides
    2. Convert DOCX → XML (apply_reference_markup sets user types in-place)
    3. Compare XML elements against reference
    4. Validate XSD with structured error details
    5. Map XSD errors to source elements (user-annotated vs auto)

    Args:
        dmc_string: DMC identifier
        input_dir: Path to doc_source directory
        output_dir: Path to output suite directory
        max_cycles: Unused (kept for API compat)
        threshold: Convergence score threshold
        llm_config: Optional LLM configuration
        progress_callback: Optional callback(cycle, total, status)

    Returns:
        List with single result dict: cycle, score, report, xsd_valid, xsd_element_issues
    """
    # Load reference
    ref_data = get_reference(dmc_string)
    if ref_data is None:
        return [{'cycle': 0, 'error': 'No reference markup saved for this DMC'}]

    ref_elements = [ElementInfo.from_dict(e) for e in ref_data['elements']
                     if e.get('type') != '_skip']
    if not ref_elements:
        return [{'cycle': 0, 'error': 'Reference has no elements'}]

    # Resolve pair info
    pair = get_pair_by_dmc(dmc_string, input_dir, output_dir)
    if not pair or not pair.get('docx_exists'):
        return [{'cycle': 0, 'error': f'DOCX not found for {dmc_string}'}]

    docx_path = pair['docx_path']

    # Determine module type from info code
    from parsers.dmc_parser import is_procedure_info_code, parse_dmc_from_folder_name, build_graphic_ident_prefix
    dmc_info = parse_dmc_from_folder_name(pair.get('folder_name', ''))
    dm_code = dmc_info['dm_code'] if dmc_info else None
    tech_name = pair.get('tech_name')
    info_name = pair.get('info_name')
    graphic_prefix = build_graphic_ident_prefix(dm_code) if dm_code else None

    module_type = 'descriptive'
    if dm_code and is_procedure_info_code(dm_code.get('infoCode', '')):
        module_type = 'procedure'

    # ── Single pass: reference markup → conversion → compare → XSD ──
    clear_overrides(dmc_string)

    print(f'\n[verify_loop] Single pass (reference markup) for {dmc_string}')

    if progress_callback:
        progress_callback(1, 1, 'converting')

    # Convert
    try:
        _run_conversion(
            docx_path=docx_path, output_dir=output_dir, dmc_string=dmc_string,
            llm_config=llm_config, dm_code=dm_code, tech_name=tech_name,
            info_name=info_name, graphic_prefix=graphic_prefix, module_type=module_type,
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f'[verify_loop] Conversion error:\n{tb}')
        return [{'cycle': 1, 'error': f'Conversion failed: {e}', 'traceback': tb}]

    # Find generated XML
    xml_path = _find_xml_for_dmc(output_dir, dmc_string)
    if not xml_path:
        return [{'cycle': 1, 'error': 'Generated XML not found after conversion'}]

    # Extract XML elements
    xml_elements = extract_xml_elements(xml_path)

    # Compare with reference
    if progress_callback:
        progress_callback(1, 1, 'comparing')

    report = compare_elements(ref_elements, xml_elements)

    print(f'[verify_loop]   Score: {report.score:.3f}  '
          f'(matched={len(report.matched_pairs)}, '
          f'left_unmatched={len(report.left_unmatched)}, '
          f'right_unmatched={len(report.right_unmatched)})')

    # XSD validation with structured errors
    xsd_valid = True
    xsd_structured = []
    xsd_element_issues = []

    try:
        from generators.s1000d_generator import S1000DGenerator
        schema = 'xsd/proced.xsd' if module_type == 'procedure' else 'xsd/descript.xsd'
        xsd_valid, xsd_structured = S1000DGenerator.validate_xml_with_details(
            xml_path, schema_file=schema)
    except Exception as e:
        xsd_structured = [{'line': 0, 'column': 0, 'message': f'XSD validation error: {e}',
                           'element_tag': None, 'element_text': None, 'xpath': None}]
        xsd_valid = False

    if not xsd_valid:
        print(f'[verify_loop]   XSD validation: FAILED ({len(xsd_structured)} errors)')
        for err in xsd_structured[:5]:
            print(f'[verify_loop]     Line {err["line"]}: {err["message"][:80]}')

        # Map XSD errors to source elements
        from parsers.elements_analyzer import get_last_markup_result
        source_elements = get_last_markup_result(dmc_string)
        if source_elements:
            xsd_element_issues = _map_xsd_to_source_elements(xsd_structured, source_elements)
            user_issues = [i for i in xsd_element_issues if i['is_user_annotated']]
            auto_issues = [i for i in xsd_element_issues if not i['is_user_annotated']]
            print(f'[verify_loop]   XSD issues: {len(user_issues)} from user markup, '
                  f'{len(auto_issues)} from auto-classification')
    else:
        print(f'[verify_loop]   XSD validation: PASSED')

    result = {
        'cycle': 1,
        'score': report.score,
        'report': report.to_dict(),
        'xsd_valid': xsd_valid,
        'xsd_element_issues': xsd_element_issues,
    }

    return [result]


# ======================================================================
# CLI entry point
# ======================================================================

def main():
    """CLI: python verify_loop.py <dmc_string> [--threshold T]"""
    import argparse

    parser = argparse.ArgumentParser(description='Run verification for a DMC')
    parser.add_argument('dmc_string', help='DMC string identifier')
    parser.add_argument('--threshold', type=float, default=None,
                        help='Convergence threshold (overrides config.ini)')
    args = parser.parse_args()

    # Read config
    config = configparser.ConfigParser()
    config.read(os.path.join(PROJECT_ROOT, 'config.ini'), encoding='utf-8')

    input_dir = os.path.join(PROJECT_ROOT,
                             config.get('processing', 'input_dir', fallback='doc_source'))
    output_dir = os.path.join(PROJECT_ROOT,
                              config.get('processing', 'output_dir', fallback='./tg_web/suites/66935'))
    threshold = args.threshold or config.getfloat('verification', 'convergence_threshold', fallback=0.95)

    llm_config = {
        'enabled': config.getboolean('llm', 'enabled', fallback=False),
        'ollama_url': config.get('llm', 'ollama_url', fallback='http://localhost:11434'),
        'ollama_model': config.get('llm', 'ollama_model', fallback='gemma3:4b-it-qat'),
        'batch_size': config.getint('llm', 'batch_size', fallback=20),
        'confidence_threshold': config.getfloat('llm', 'confidence_threshold', fallback=0.7),
        'cache_enabled': config.getboolean('llm', 'cache_enabled', fallback=True),
        'cache_dir': config.get('llm', 'cache_dir', fallback='.llm_cache'),
    }

    print(f'Running verification for {args.dmc_string}')
    print(f'  Input dir:  {input_dir}')
    print(f'  Output dir: {output_dir}')
    print(f'  Threshold:  {threshold}')

    results = run_verification_loop(
        dmc_string=args.dmc_string,
        input_dir=input_dir,
        output_dir=output_dir,
        threshold=threshold,
        llm_config=llm_config,
    )

    # Print summary
    print('\n' + '=' * 60)
    print('Verification results:')
    for r in results:
        if 'error' in r:
            print(f"  ERROR: {r['error']}")
        else:
            xsd_status = 'PASS' if r.get('xsd_valid') else 'FAIL'
            issues = r.get('xsd_element_issues', [])
            user_issues = [i for i in issues if i.get('is_user_annotated')]
            print(f"  Score: {r['score']:.3f}  XSD: {xsd_status}")
            if user_issues:
                print(f"  XSD issues from user markup: {len(user_issues)}")
                for iss in user_issues[:5]:
                    print(f"    - [{iss['user_type']}] \"{iss['text_preview']}\" — {iss['xsd_error'][:60]}")
    print('=' * 60)

    # Return exit code based on final score
    if results and 'score' in results[-1]:
        final_score = results[-1]['score']
        sys.exit(0 if final_score >= threshold else 1)
    else:
        sys.exit(2)


if __name__ == '__main__':
    main()
