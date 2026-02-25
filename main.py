"""
Main entry point for Word to S1000D conversion.
Supports single-file mode and batch processing of all folders in input_dir.
"""

from typing import Dict, List, Optional
import sys
import os
import logging
import configparser

from parsers.dmc_parser import (
    parse_dmc_from_folder_name,
    is_descriptive_info_code,
    is_procedure_info_code,
    build_graphic_ident_prefix,
    dm_code_to_string,
)


def determine_module_type(doc_path: str) -> str:
    """
    Determine the type of data module to create from the document.

    This is a stub function that will be expanded for different module types:
    - Descriptive modules (current implementation)
    - Task modules (technological maps)
    - Fault isolation modules
    - Maintenance procedures

    Args:
        doc_path: Path to the source document

    Returns:
        Module type identifier
    """
    # For now, assume all documents are descriptive modules
    # Later, this could analyze document content/structure to determine type
    return "descriptive"


def get_llm_config(config: configparser.ConfigParser) -> Dict:
    """
    Extract LLM configuration from config parser.

    Args:
        config: ConfigParser object

    Returns:
        Dict with LLM configuration
    """
    llm_config = {
        'enabled': config.getboolean('llm', 'enabled', fallback=False),
        'ollama_url': config.get('llm', 'ollama_url', fallback='http://localhost:11434'),
        'ollama_model': config.get('llm', 'ollama_model', fallback='gemma3:4b-it-qat'),
        'batch_size': config.getint('llm', 'batch_size', fallback=20),
        'confidence_threshold': config.getfloat('llm', 'confidence_threshold', fallback=0.7),
        'cache_enabled': config.getboolean('llm', 'cache_enabled', fallback=True),
        'cache_dir': config.get('llm', 'cache_dir', fallback='.llm_cache')
    }
    return llm_config


def route_to_processor(module_type: str, doc_path: str, output_dir: str, llm_config: Dict = None):
    """
    Route to appropriate processing script based on module type.

    Args:
        module_type: Type of module to create
        doc_path: Path to source document
        output_dir: Output directory for generated files
        llm_config: Optional LLM configuration dict
    """
    if module_type == "descriptive":
        # Import and run descriptive module processor
        from processing_scripts import descriptive_processor
        descriptive_processor.process_descriptive_document(doc_path, output_dir, llm_config=llm_config)
    elif module_type in ("task", "procedure"):
        from processing_scripts import procedure_processor
        procedure_processor.process_procedure_document(doc_path, output_dir, llm_config=llm_config)
    elif module_type == "fault_isolation":
        # Future: fault isolation module processor
        print("Fault isolation module processing not implemented yet")
    elif module_type == "maintenance":
        # Future: maintenance procedure module processor
        print("Maintenance module processing not implemented yet")
    else:
        print(f"Unknown module type: {module_type}")


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def setup_logging(output_dir: str) -> logging.Logger:
    """Configure logging to both console and file."""
    logger = logging.getLogger('word_to_s1000d')
    logger.setLevel(logging.DEBUG)

    # Remove existing handlers to avoid duplicates on re-runs
    logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    logger.addHandler(console_handler)

    # File handler
    _logs_dir = os.path.join(output_dir, '_logs')
    os.makedirs(_logs_dir, exist_ok=True)
    log_file = os.path.join(_logs_dir, 'batch_processing.log')
    file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='w')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(file_handler)

    return logger


def find_docx_in_folder(folder_path: str) -> Optional[str]:
    """
    Find the primary .docx file at the root level of a folder.
    Skips known metadata files (e.g. signatureListVED.docx).

    Returns:
        Path to .docx file or None if not found.
    """
    skip_names = {'signaturelistved.docx'}
    for f in os.listdir(folder_path):
        full_path = os.path.join(folder_path, f)
        if os.path.isfile(full_path) and f.lower().endswith('.docx') and f.lower() not in skip_names:
            return full_path
    return None


def find_doc_in_folder(folder_path: str) -> Optional[str]:
    """Find old-format .doc file at the root level of a folder.

    Returns:
        Full path to .doc file or None if not found.
    """
    for f in os.listdir(folder_path):
        full_path = os.path.join(folder_path, f)
        if os.path.isfile(full_path) and f.lower().endswith('.doc') and not f.lower().endswith('.docx'):
            return full_path
    return None


def collect_batch_tasks(input_dir: str) -> List[Dict]:
    """
    Scan input_dir for processable folders.

    Returns list of task dicts:
        folder_path, folder_name, docx_path, dmc_info, skip_reason
    """
    tasks = []
    for entry in sorted(os.listdir(input_dir)):
        folder_path = os.path.join(input_dir, entry)
        if not os.path.isdir(folder_path):
            continue

        task = {
            'folder_path': folder_path,
            'folder_name': entry,
            'dmc_info': None,
            'docx_path': None,
            'skip_reason': None,
        }

        # Try to parse DMC from folder name
        dmc_info = parse_dmc_from_folder_name(entry)
        task['dmc_info'] = dmc_info

        if dmc_info is None:
            task['skip_reason'] = 'Нет кода DMC в имени папки'
            tasks.append(task)
            continue

        info_code = dmc_info['dm_code']['infoCode']
        if is_descriptive_info_code(info_code):
            task['module_type'] = 'descriptive'
        elif is_procedure_info_code(info_code):
            task['module_type'] = 'procedure'
        else:
            task['skip_reason'] = f'Неизвестный тип модуля (infoCode={info_code})'
            tasks.append(task)
            continue

        docx_path = find_docx_in_folder(folder_path)
        if docx_path is None:
            doc_path = find_doc_in_folder(folder_path)
            if doc_path:
                # .doc найден — будет сконвертирован в .docx перед обработкой
                task['doc_path'] = doc_path
                task['needs_conversion'] = True
            else:
                task['skip_reason'] = 'Нет .docx/.doc файла в папке'
            tasks.append(task)
            continue

        task['docx_path'] = docx_path
        tasks.append(task)

    return tasks


def convert_doc_tasks(tasks: List[Dict]):
    """
    Convert .doc files to .docx for tasks that need it.
    Updates task dicts in-place: sets docx_path on success, skip_reason on failure.
    """
    from parsers.doc_converter import convert_doc_to_docx_batch

    file_pairs = []
    for task in tasks:
        doc_path = task['doc_path']
        docx_path = os.path.splitext(doc_path)[0] + '.docx'
        file_pairs.append((doc_path, docx_path))

    results = convert_doc_to_docx_batch(file_pairs)

    for task, (target_path, success, error_msg) in zip(tasks, results):
        if success:
            task['docx_path'] = target_path
            task['skip_reason'] = None
            task.pop('needs_conversion', None)
        else:
            task['skip_reason'] = f'Ошибка конвертации .doc -> .docx: {error_msg}'
            task.pop('needs_conversion', None)


def clear_output_dir(output_dir: str):
    """Clear output directory files (not subdirectories) before batch generation."""
    if os.path.exists(output_dir):
        for file_name in os.listdir(output_dir):
            file_path = os.path.join(output_dir, file_name)
            if os.path.isfile(file_path):
                os.unlink(file_path)
    else:
        os.makedirs(output_dir)


def run_batch(config: configparser.ConfigParser, input_dir: str, output_dir: str):
    """Run batch processing of all S1000D-coded folders in input_dir."""
    # Ensure output directory exists before setting up logging
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    logger = setup_logging(output_dir)
    llm_config = get_llm_config(config)

    if llm_config['enabled']:
        logger.info(f"LLM включен: {llm_config['ollama_model']} на {llm_config['ollama_url']}")

    # Collect tasks
    logger.info(f"Сканирование папки: {input_dir}")
    tasks = collect_batch_tasks(input_dir)
    total = len(tasks)

    # Convert .doc files to .docx where needed
    needs_conversion = [t for t in tasks if t.get('needs_conversion')]
    if needs_conversion:
        logger.info(f"Найдено .doc файлов для конвертации: {len(needs_conversion)}")
        convert_doc_tasks(needs_conversion)

    processable = [t for t in tasks if t['skip_reason'] is None]
    skipped = [t for t in tasks if t['skip_reason'] is not None]

    logger.info(f"Найдено папок: {total}, к обработке: {len(processable)}, пропущено: {len(skipped)}")
    logger.info("")

    for task in skipped:
        logger.info(f"  ПРОПУСК: {task['folder_name']}")
        logger.info(f"           Причина: {task['skip_reason']}")

    if not processable:
        logger.warning("Нет файлов для обработки.")
        return

    # Close logger before clearing output directory (to release file lock)
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)

    # Clear output directory once before processing
    clear_output_dir(output_dir)

    # Re-create logger after clearing
    logger = setup_logging(output_dir)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Начало пакетной обработки")
    logger.info("=" * 60)

    # Process each task
    all_dm_refs = []
    all_illustrations = {}

    for idx, task in enumerate(processable, 1):
        dmc_info = task['dmc_info']
        dm_code = dmc_info['dm_code']
        graphic_prefix = build_graphic_ident_prefix(dm_code)

        logger.info("")
        logger.info(f"[{idx}/{len(processable)}] Обработка: {task['folder_name']}")
        logger.info(f"  DMC: {dm_code_to_string(dm_code)}")
        logger.info(f"  Файл: {os.path.basename(task['docx_path'])}")
        logger.info(f"  techName: {dmc_info['tech_name']}")
        logger.info(f"  infoName: {dmc_info['info_name']}")

        try:
            module_type = task.get('module_type', 'descriptive')
            if module_type == 'procedure':
                from processing_scripts import procedure_processor
                dm_refs, illustrations = procedure_processor.process_procedure_document(
                    doc_path=task['docx_path'],
                    output_dir=output_dir,
                    llm_config=llm_config,
                    dm_code_override=dm_code,
                    tech_name_override=dmc_info['tech_name'],
                    info_name_override=dmc_info['info_name'],
                    skip_pmc=True,
                    graphic_ident_prefix=graphic_prefix,
                )
            else:
                from processing_scripts import descriptive_processor
                dm_refs, illustrations = descriptive_processor.process_descriptive_document(
                    doc_path=task['docx_path'],
                    output_dir=output_dir,
                    llm_config=llm_config,
                    dm_code_override=dm_code,
                    tech_name_override=dmc_info['tech_name'],
                    info_name_override=dmc_info['info_name'],
                    skip_pmc=True,
                    graphic_ident_prefix=graphic_prefix,
                )
            all_dm_refs.extend(dm_refs)
            all_illustrations.update(illustrations)
            logger.info(f"  УСПЕХ: Сгенерировано {len(dm_refs)} модуль(ей) данных ({module_type})")
        except Exception as e:
            logger.error(f"  ОШИБКА: {task['folder_name']} — {e}", exc_info=True)

    # Generate consolidated PMC
    if all_dm_refs:
        from generators.pm_generator import PMGenerator, create_pm_config

        pm_generator = PMGenerator()
        model_code = all_dm_refs[0]['dm_code'].get('modelIdentCode', 'S5')
        pm_config = create_pm_config(
            model_ident_code=model_code,
            pm_title='Руководство',
        )
        pm_filepath = pm_generator.generate_publication_module(
            pm_config, all_dm_refs, output_dir, all_illustrations
        )
        logger.info(f"Сгенерирован PMC: {os.path.basename(pm_filepath)}")

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Пакетная обработка завершена")
    logger.info(f"  Обработано: {len(processable)}")
    logger.info(f"  Пропущено: {len(skipped)}")
    logger.info(f"  Всего модулей данных: {len(all_dm_refs)}")
    logger.info("=" * 60)

    # Close logger before moving log files
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)

    # Move non-XML files to _logs subdirectory so that the viewer backend
    # only sees .xml files in the suite directory
    move_logs_to_subdir(output_dir)


def move_logs_to_subdir(output_dir: str):
    """Move non-XML files from output_dir to _logs subdirectory."""
    logs_dir = os.path.join(output_dir, '_logs')
    xml_extensions = {'.xml'}
    for fname in os.listdir(output_dir):
        fpath = os.path.join(output_dir, fname)
        if not os.path.isfile(fpath):
            continue
        _, ext = os.path.splitext(fname)
        if ext.lower() not in xml_extensions:
            if not os.path.exists(logs_dir):
                os.makedirs(logs_dir)
            os.replace(fpath, os.path.join(logs_dir, fname))


# ---------------------------------------------------------------------------
# Single-file processing (legacy mode)
# ---------------------------------------------------------------------------

def run_single_file(config: configparser.ConfigParser, doc_path: str, output_dir: str):
    """Process a single document file (original behavior)."""
    if not os.path.exists(doc_path):
        print(f"Ошибка: Файл не найден: {doc_path}")
        sys.exit(1)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    else:
        # Clear output directory before generation
        for file_name in os.listdir(output_dir):
            file_path = os.path.join(output_dir, file_name)
            if os.path.isfile(file_path):
                os.unlink(file_path)

    # Determine module type
    module_type = determine_module_type(doc_path)
    print(f"Detected module type: {module_type}")

    # Get LLM configuration
    llm_config = get_llm_config(config)
    if llm_config['enabled']:
        print(f"LLM enabled: {llm_config['ollama_model']} at {llm_config['ollama_url']}")

    # Route to appropriate processor
    route_to_processor(module_type, doc_path, output_dir, llm_config=llm_config)


def main():
    """Main entry point."""
    # Read configuration
    config = configparser.ConfigParser()
    config.read('config.ini', encoding='utf-8')
    output_dir = config.get('processing', 'output_dir', fallback='./tg_web/publications')
    input_dir = config.get('processing', 'input_dir', fallback='./docs')

    if len(sys.argv) == 2:
        # Single file mode (CLI argument)
        doc_path = sys.argv[1]
        run_single_file(config, doc_path, output_dir)
    elif len(sys.argv) > 2:
        print("Usage: python main.py [<docx_file>]")
        print("  No argument + docx_file commented out in config.ini -> batch mode")
        print("  No argument + docx_file set in config.ini -> single-file mode")
        print("  <docx_file> argument -> single-file mode")
        sys.exit(1)
    elif config.has_option('processing', 'docx_file'):
        # Single file mode (from config)
        docx_file = config.get('processing', 'docx_file')
        doc_path = os.path.join(input_dir, docx_file)
        run_single_file(config, doc_path, output_dir)
    else:
        # Batch mode — no specific file, process entire input_dir
        run_batch(config, input_dir, output_dir)


if __name__ == "__main__":
    main()
