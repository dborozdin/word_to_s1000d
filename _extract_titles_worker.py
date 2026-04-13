"""Воркер для извлечения заголовков из Word-документов.

Запускается как subprocess для изоляции Word COM от Flask-процесса.
Вход: JSON через stdin — список объектов {filepath, doc_type}
Выход: JSON через stdout — {results: {filepath: title}, errors: [{file, error}], word_restarts: N}
"""
import json
import os
import re
import subprocess
import sys
import time


BATCH_SIZE = 5
MAX_RETRIES = 2
RESTART_DELAY = 2.0

# Строки-шаблоны колонтитулов (пропускаем)
_SKIP_PARAGRAPHS = {
    'су-57', 'руководство по технической эксплуатации',
    'руководство по техническому обслуживанию',
}


def _kill_word():
    """Принудительно завершает все процессы winword.exe."""
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'WINWORD.EXE'],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def _start_word(pythoncom, win32com_client):
    """Запускает Word COM с надёжными настройками."""
    word = win32com_client.Dispatch('Word.Application')
    word.Visible = False
    word.DisplayAlerts = 0  # wdAlertsNone
    return word


def _stop_word(word):
    """Останавливает Word, при неудаче — kill."""
    if not word:
        return
    try:
        word.Quit()
        time.sleep(0.5)
    except Exception:
        _kill_word()
        time.sleep(1.0)


def _to_sentence_case(text):
    """Приводит текст к регистру 'как в предложении'.

    - ALL CAPS текст → lowercase + заглавная первая буква
    - Смешанный регистр (уже нормальный) → оставить как есть
    - Коды/обозначения с цифрами и точками → сохранить
    """
    if not text:
        return text

    # Проверяем: текст целиком в верхнем регистре?
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return text
    upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)

    # Если <70% заглавных — текст уже в нормальном регистре
    if upper_ratio < 0.7:
        return text

    # ALL CAPS → sentence case
    result = text.lower()

    # Первая буква — заглавная
    for i, c in enumerate(result):
        if c.isalpha():
            result = result[:i] + c.upper() + result[i+1:]
            break

    # Заглавная после тире/двоеточия
    for sep in ('– ', '— ', ': '):
        parts = result.split(sep)
        if len(parts) > 1:
            fixed = [parts[0]]
            for part in parts[1:]:
                if part and part[0].isalpha():
                    part = part[0].upper() + part[1:]
                fixed.append(part)
            result = sep.join(fixed)

    return result


def _clean_title(text):
    """Очистка и нормализация заголовка."""
    text = text.strip()
    text = text.replace('\r', '').replace('\x07', '').replace('\x0b', ' ')
    text = text.replace('\u2212', '\u2013').replace('\u2012', '\u2013')
    text = re.sub(r'\s+', ' ', text).strip()
    text = _to_sentence_case(text)
    text = text.rstrip('.')
    return text


def _extract_tk_title(doc):
    """Ищет «Наименование работы» в Shape TextFrames."""
    for i in range(1, doc.Shapes.Count + 1):
        try:
            shape = doc.Shapes(i)
            if shape.TextFrame.HasText:
                text = shape.TextFrame.TextRange.Text
                m = re.search(
                    r'[Нн]аименование\s+работы\s*(.+?)(?:[Тт]рудоёмкость|$)',
                    text, re.DOTALL
                )
                if m:
                    return m.group(1).strip()
        except Exception:
            pass
    return ''


def _extract_first_paragraph(doc):
    """Первый содержательный параграф."""
    for i in range(1, min(15, doc.Paragraphs.Count + 1)):
        try:
            text = doc.Paragraphs(i).Range.Text.strip()
            if not text or len(text) < 4:
                continue
            if text.lower().rstrip('.') in _SKIP_PARAGRAPHS:
                continue
            if re.match(r'^\d+\.?\s', text):
                continue
            return text
        except Exception:
            continue
    return ''


def _extract_one(word, filepath, doc_type):
    """Извлекает заголовок из одного файла. Возвращает (title, error_or_None)."""
    doc = None
    try:
        doc = word.Documents.Open(
            os.path.abspath(filepath),
            ReadOnly=True,
            AddToRecentFiles=False,
            ConfirmConversions=False
        )

        if doc_type == 'tk':
            title = _extract_tk_title(doc)
            if title:
                return _clean_title(title), None

        title = _extract_first_paragraph(doc)
        if title:
            return _clean_title(title), None

        return '', None  # пустой заголовок — не ошибка
    except Exception as e:
        err = str(e)
        is_rpc = 'RPC' in err or '-2147023174' in err or 'Call was rejected' in err or '-2146959355' in err
        return None if is_rpc else '', err
    finally:
        if doc:
            try:
                doc.Close(False)
            except Exception:
                pass


def main():
    # Фиксируем кодировку для Windows
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

    import pythoncom
    import win32com.client

    input_data = json.loads(sys.stdin.read())
    files = input_data  # [{filepath, doc_type}, ...]

    results = {}  # filepath → title
    errors = []   # [{file, error}]
    word_restarts = 0

    pythoncom.CoInitialize()
    word = None

    try:
        for i, item in enumerate(files):
            filepath = item['filepath']
            doc_type = item['doc_type']
            fname = os.path.basename(filepath)

            # Перезапуск Word каждые BATCH_SIZE файлов
            if word is None or i % BATCH_SIZE == 0:
                _stop_word(word)
                if i > 0:
                    time.sleep(RESTART_DELAY)
                    word_restarts += 1
                word = _start_word(pythoncom, win32com.client)

            # Попытка с retry
            title = None
            last_err = ''
            for attempt in range(MAX_RETRIES + 1):
                result, err = _extract_one(word, filepath, doc_type)

                if result is not None:
                    title = result
                    break

                # COM упал — перезапуск
                last_err = err or 'COM failure'
                print(f"  [{fname}] attempt {attempt+1} failed: {last_err}", file=sys.stderr)
                _stop_word(word)
                _kill_word()
                time.sleep(RESTART_DELAY)
                word_restarts += 1
                try:
                    word = _start_word(pythoncom, win32com.client)
                except Exception as e:
                    last_err = f'Word restart failed: {e}'
                    word = None
                    break

            if title:
                results[filepath] = title
            elif title == '':
                # Пустой заголовок — не ошибка, просто не нашли
                errors.append({'file': fname, 'error': 'заголовок не найден в документе'})
            else:
                errors.append({'file': fname, 'error': last_err})

    except Exception as e:
        errors.append({'file': '(критическая ошибка)', 'error': str(e)})
    finally:
        _stop_word(word)
        pythoncom.CoUninitialize()

    output = {
        'results': results,
        'errors': errors,
        'word_restarts': word_restarts,
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
