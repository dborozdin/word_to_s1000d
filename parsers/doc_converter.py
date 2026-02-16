"""
Конвертер .doc файлов в .docx через Microsoft Word COM Automation.
Требует установленного Microsoft Word и библиотеки pywin32.
"""

import os
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger('word_to_s1000d')


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

    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0

        doc = word.Documents.Open(source_path)
        doc.SaveAs2(target_path, FileFormat=16)  # 16 = wdFormatXMLDocument (.docx)
        doc.Close()
        logger.info(f"  Конвертирован: {os.path.basename(source_path)} -> {os.path.basename(target_path)}")
    except Exception as e:
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
            try:
                doc = word.Documents.Open(source_path)
                doc.SaveAs2(target_path, FileFormat=16)
                doc.Close()
                results.append((target_path, True, ""))
                logger.info(f"  Конвертирован: {os.path.basename(source_path)} -> {os.path.basename(target_path)}")
            except Exception as e:
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
