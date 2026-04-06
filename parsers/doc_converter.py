"""
Конвертер .doc файлов в .docx через Microsoft Word COM Automation.
Требует установленного Microsoft Word и библиотеки pywin32.
"""

import os
import logging
import tempfile
import shutil
from typing import List, Optional, Tuple

logger = logging.getLogger('word_to_s1000d')

_MAX_PATH = 255  # Word's own limit is 255, stricter than Windows 260


def _get_short_path(long_path: str) -> str:
    """Get Windows 8.3 short path to bypass MAX_PATH limitation."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(512)
        ret = ctypes.windll.kernel32.GetShortPathNameW(long_path, buf, 512)
        if ret > 0:
            return buf.value
    except Exception:
        pass
    return long_path


def _safe_paths_for_word(source: str, target: str):
    """Return (source, target, cleanup_fn) safe for Win32COM.

    If paths exceed MAX_PATH and short path works, use short paths.
    Otherwise copy source to temp dir, convert there, then move result back.
    """
    src_abs = os.path.abspath(source)
    tgt_abs = os.path.abspath(target)

    # Fast path: both within MAX_PATH
    if len(src_abs) <= _MAX_PATH and len(tgt_abs) <= _MAX_PATH:
        return src_abs, tgt_abs, None

    # Try short paths
    src_short = _get_short_path(src_abs)
    tgt_short = _get_short_path(os.path.dirname(tgt_abs))
    if tgt_short != os.path.dirname(tgt_abs):
        tgt_short = os.path.join(tgt_short, os.path.basename(tgt_abs))
    else:
        tgt_short = tgt_abs

    if len(src_short) <= _MAX_PATH and len(tgt_short) <= _MAX_PATH:
        return src_short, tgt_short, None

    # Fallback: copy to temp dir
    tmp_dir = tempfile.mkdtemp(prefix='doc_conv_')
    tmp_src = os.path.join(tmp_dir, 'input.doc')
    tmp_tgt = os.path.join(tmp_dir, 'output.docx')
    shutil.copy2(src_abs, tmp_src)

    def cleanup(success):
        if success and os.path.isfile(tmp_tgt):
            os.makedirs(os.path.dirname(tgt_abs), exist_ok=True)
            shutil.move(tmp_tgt, tgt_abs)
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return tmp_src, tmp_tgt, cleanup


def convert_doc_to_docx(source_path: str, target_path: Optional[str] = None) -> str:
    """
    Конвертирует .doc файл в .docx через COM-объект Microsoft Word.

    Args:
        source_path: Путь к исходному .doc файлу
        target_path: Путь для сохранения .docx (если None — рядом с исходным)

    Returns:
        Путь к сконвертированному .docx файлу

    Raises:
        RuntimeError: Если конвертация не удалась
    """
    import pythoncom
    import win32com.client

    source_path = os.path.abspath(source_path)
    if target_path is None:
        target_path = os.path.splitext(source_path)[0] + '.docx'
    else:
        target_path = os.path.abspath(target_path)

    safe_src, safe_tgt, cleanup = _safe_paths_for_word(source_path, target_path)

    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0

        doc = word.Documents.Open(safe_src)
        doc.SaveAs2(safe_tgt, FileFormat=16)  # 16 = wdFormatXMLDocument (.docx)
        doc.Close()
        if cleanup:
            cleanup(True)
        logger.info(f"  Конвертирован: {os.path.basename(source_path)} -> {os.path.basename(target_path)}")
    except Exception as e:
        if cleanup:
            cleanup(False)
        raise RuntimeError(f"Ошибка конвертации {source_path}: {e}") from e
    finally:
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()

    return target_path


def convert_doc_to_docx_batch(file_pairs: List[Tuple[str, str]]) -> List[Tuple[str, bool, str]]:
    """
    Пакетная конвертация .doc -> .docx через один экземпляр Word.

    Args:
        file_pairs: Список кортежей (source_path, target_path)

    Returns:
        Список кортежей (target_path, success, error_message)
    """
    if not file_pairs:
        return []

    import pythoncom
    import win32com.client

    results = []
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0

        for source_path, target_path in file_pairs:
            source_path = os.path.abspath(source_path)
            target_path = os.path.abspath(target_path)
            safe_src, safe_tgt, cleanup = _safe_paths_for_word(source_path, target_path)
            try:
                doc = word.Documents.Open(safe_src)
                doc.SaveAs2(safe_tgt, FileFormat=16)
                doc.Close()
                if cleanup:
                    cleanup(True)
                results.append((target_path, True, ""))
                logger.info(f"  Конвертирован: {os.path.basename(source_path)} -> {os.path.basename(target_path)}")
            except Exception as e:
                if cleanup:
                    cleanup(False)
                results.append((target_path, False, str(e)))
                logger.error(f"  Ошибка конвертации {os.path.basename(source_path)}: {e}")
    except Exception as e:
        # Word не удалось запустить — все файлы помечаем как неудачные
        for source_path, target_path in file_pairs:
            if not any(r[0] == os.path.abspath(target_path) for r in results):
                results.append((os.path.abspath(target_path), False, str(e)))
        logger.error(f"  Не удалось запустить Microsoft Word: {e}")
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

    return results
