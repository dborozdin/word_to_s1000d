"""
Преобразование сырой папки документов в структуру S1000D.

Берёт папку с сырыми исходниками (doc_source_29_raw/) и создаёт
двухуровневую структуру папок с DMC-кодами, пригодную для импорта
через основной pipeline (main.py).

Использование:
  python raw_to_structured.py --input doc_source_29_raw --output doc_source_29_generated
  python raw_to_structured.py --input doc_source_29_raw --output doc_source_29_generated --validate doc_source_29_reference
"""

import argparse
import configparser
import difflib
import os
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RawDocument:
    filepath: str
    filename: str
    system_code: str        # "029"
    subsystem_code: str     # "11"
    component_code: str     # "01"
    doc_type: str           # "description" | "tk" | "piun" | "tk_to" | "special" | "graphic"
    tk_number: Optional[int] = None
    title_text: str = ""    # оставшаяся часть имени после кодов
    special_type: Optional[str] = None  # "abbreviations", "piun", "tk_to"


@dataclass
class DataModule:
    """Один модуль данных — одна папка Level 2."""
    system_code: str
    subsystem_code: str
    component_code: str
    assy_code: str          # "00" или "01" (фильтроэлемент)
    disassy_code: str       # "00" по умолчанию, "01"-"05" для ПИУН
    info_code: str          # "040", "920", ...
    info_variant: str       # "A", "B"
    component_name: str     # "Гидрокомпенсатор"
    info_name: str          # "Описание устройства и принципа действия"
    source_files: List[str] = field(default_factory=list)


@dataclass
class Component:
    system_code: str
    subsystem_code: str
    component_code: str
    name: str
    data_modules: List[DataModule] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

DEFAULT_MODEL_IDENT = "S5"
DEFAULT_SYSTEM_DIFF = "A"
DEFAULT_ITEM_LOCATION = "A"

# Полные названия компонентов (извлечены из reference).
# Ключ: (subsystem_code, component_code), значение: полное название
COMPONENT_NAMES_029: Dict[Tuple[str, str], str] = {
    ('00', '00'): 'Гидравлическая система',
    ('11', '00'): 'Первая гидросистема',
    ('11', '01'): 'Гидрокомпенсатор',
    ('11', '02'): 'Гидроаккумулятор',
    ('11', '03'): 'Бортовой клапан 991АТ4.02А-01',
    ('11', '04'): 'Бортовой клапан всасывания',
    ('11', '05'): 'Бортовой клапан нагнетания',
    ('11', '06'): 'Топливо-масляный теплообменник',
    ('11', '07'): 'Плунжерный насос НП173',
    ('11', '08'): 'Гидравлический фильтр слива НП ЖКДЕ.061146.011С',
    ('11', '09'): 'Гидравлический фильтр нагнетания ЖКДЕ.061146.010С',
    ('11', '10'): 'Гидравлический фильтр слива ЖКДЕ.061146.012С-01',
    ('11', '11'): 'Двухсторонний дроссель 50.5313.0.180.000',
    ('11', '12'): 'Распределитель электрогидравлический трехпозиционный четырехходовой КЭ101',
    ('11', '13'): 'Предохранительный клапан 50.5309.0.080.000',
    ('11', '14'): 'Клапан предохранительный РД66',
    ('11', '15'): 'Клапан стравливания 50.5309.0.050.000',
    ('11', '16'): 'Обратный клапан 990-7',
    ('11', '17'): 'Рукав фторопластовый',
    ('11', '18'): 'Клапан переключения с электромагнитным управлением КГ48-2',
    ('12', '00'): 'Вторая гидросистема',
    ('12', '01'): 'Челночный клапан УГ157',
    ('12', '02'): 'Насосная станция НС74-2',
    ('30', '00'): 'Система сигнализации гидросистемы',
    ('30', '01'): 'Датчик давления ДАВ096',
    ('30', '02'): 'Датчик температуры П-119',
    ('30', '03'): 'Манометр недистанционный НТМ-400',
    ('30', '04'): 'Сигнализатор давления типа СДМ',
    ('30', '05'): 'Датчик линейных перемещений ПЛЦ007',
}

# Стандартные info-names для info-кодов
INFO_NAMES: Dict[str, str] = {
    '005': 'Перечень принятых сокращений',
    '012': 'Меры безопасности',
    '040': 'Описание устройства и принципа действия',
    '042': 'Описание устройства и принципа действия',
    '222': 'Слив рабочей жидкости',
    '224': 'Разрядка пневмополости',
    '227': 'Стравливание давления из гидрополости',
    '231': 'Удаление воздуха',
    '242': 'Смазка уплотнительных колец газовой полости',
    '311': 'Осмотр внешнего состояния',
    '320': 'Проверка работоспособности',
    '341': 'Проверка работоспособности',
    '364': 'Проверка герметичности',
    '369': 'Контроль количества воздуха в системе',
    '371': 'Проверка чистоты и вязкости рабочей жидкости',
    '420': 'Восстановление работоспособности',
    '720': 'Общие указания при монтаже фторопластовых рукавов',
    '721': 'Монтаж арматуры на гидроагрегатах при их замене',
    '730': 'Подключение второго канала',
    '920': 'Демонтаж и монтаж',
    '922': 'Демонтаж и монтаж',
    '926': 'Подключение и отключение наземной гидроустановки',
}

# Описания неисправностей для модулей ПИУН (disassyCode 01..05)
PIUN_MODULES = [
    ('01', 'Недозаправка 1ГС (2ГС)', 'Устранение неисправности'),
    ('02', 'ВОЗДУХ в 1 ГС (2ГС)', 'Устранение неисправности'),
    ('03', 'Отсутствие показаний на мнемокадре ГПС уровня заправки гидрокомпенсатора 1ГС (2ГС)', 'Устранение неисправности'),
    ('04', 'Отсутствие показаний на мнемокадре ГПС давления 1ГС (2ГС)', 'Устранение неисправности'),
    ('05', 'Отсутствие показаний на мнемокадре ГПС давления в гидроаккумуляторе 1ГС (2ГС)', 'Устранение неисправности'),
]

# Разбиение ТК ТО на 3 модуля
TK_TO_MODULES = [
    ('012', 'A', 'Меры безопасности'),
    ('720', 'A', 'Общие указания при монтаже фторопластовых рукавов'),
    ('920', 'A', 'Общие указания при проведении демонтажно-монтажных работ'),
]


# ---------------------------------------------------------------------------
# Правила назначения info-кодов
# ---------------------------------------------------------------------------

# (required_keywords, excluded_keywords, info_code, info_variant, priority)
INFO_CODE_RULES = [
    (['демонтаж'], [], '920', 'A', 10),
    (['дм '], [], '920', 'A', 9),          # "ДМ" = сокращение от "демонтаж-монтаж"
    (['смазк'], [], '242', 'A', 10),
    (['герметичност'], [], '364', 'A', 10),
    (['разрядк'], [], '224', 'A', 10),
    (['стравливан'], [], '227', 'A', 10),
    (['слив'], ['фильтр'], '222', 'A', 10),
    (['удален', 'воздух'], [], '231', 'A', 11),
    (['подключен', 'наземн'], [], '926', 'A', 11),
    (['подключен', 'канал'], [], '730', 'A', 11),
    (['монтаж', 'арматур'], [], '721', 'A', 11),
    (['восстановлен'], [], '420', 'A', 10),
    (['визуальн', 'осмотр'], [], '311', 'B', 11),
    (['осмотр'], ['визуальн'], '311', 'A', 10),
    (['контрол', 'воздух'], [], '369', 'A', 11),
    (['чистот'], [], '371', 'A', 10),
    (['электромагнитн'], [], '341', 'A', 10),
    (['работоспособност'], [], '341', 'A', 8),
]

# Overrides: (system_code, subsystem_pattern, component_pattern, base_info_code) → new_info_code
OVERRIDES = {
    ('029', '30', '05', '040'): '042',   # ПЛЦ → 042A
    ('029', '12', '02', '920'): '922',   # НС74-2 → 922A
    ('029', '30', '*', '341'): '320',    # сигнализация → 320A
}


def sanitize(name: str) -> str:
    """Убирает символы, недопустимые в именах папок Windows."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name).strip()


def _long_path(p: str) -> str:
    r"""Add \\?\ prefix for Windows extended-length path support (>260 chars)."""
    from app_paths import long_path
    return long_path(p)


# ---------------------------------------------------------------------------
# Этап 1: Парсинг файлов
# ---------------------------------------------------------------------------

# Regex для файлов описаний
# Обрабатывает: "029.11.01 описание гидрокомпенсатор !.doc",
#               "029.11.02 описани гидроаккумул !.doc",
#               "029.11.16 обратный клапан 990-7 !.doc",
#               "029.00.00 описание.docx!.doc" (нестандартное расширение)
RE_DESCRIPTION = re.compile(
    r'^(\d{3})[.\-](\d{2})[.\-](\d{2})\s+'
    r'(?:описани\S*|обратный\s+клапан)\s*'
    r'(.*?)\s*(?:!)?\s*'
    r'\.(?:docx?!?\.)?(docx?|pdf)$',
    re.IGNORECASE
)

# Regex для ТК (технологических карт)
RE_TK = re.compile(
    r'^(\d{3})[.\-](\d{2})[.\-](\d{2})\s+'
    r'ТК\s*(\d+)\s*'
    r'(.*?)\s*(?:!)?'
    r'\.(docx?|pdf)$',
    re.IGNORECASE
)

# Regex для рисунков
RE_GRAPHIC = re.compile(
    r'^0?(\d{2,3})[.\-](\d{2})[.\-](\d{2})\s+'
    r'(?:рисунок|рис)\s*(\d+)\s*'
    r'(.*?)\s*(?:!)?'
    r'\.(cdr|jpg|png)$',
    re.IGNORECASE
)

# Regex для рисунков ПИУН
RE_PIUN_GRAPHIC = re.compile(
    r'^(\d{3})[.\-](\d{2})[.\-](\d{2})\s+'
    r'ПИУН\s+рис\s*(\d+)'
    r'.*\.(cdr|jpg|png)$',
    re.IGNORECASE
)

# Regex для файлов-описаний без ключевого слова (только код компонента)
# Обрабатывает: "012-00-00.doc", "012.02.01.docx"
RE_PLAIN_DESCRIPTION = re.compile(
    r'^(\d{3})[.\-](\d{2})[.\-](\d{2})\s*\.(docx?|pdf)$',
    re.IGNORECASE
)

# Regex для таблиц
# Обрабатывает: "012-00-00 Таблица 1.doc", "012.00.00 Таблица 2.docx"
RE_TABLE = re.compile(
    r'^(\d{3})[.\-](\d{2})[.\-](\d{2})\s+'
    r'Таблица\s*(\d+)'
    r'.*\.(docx?|pdf)$',
    re.IGNORECASE
)

# Regex для имён компонентных папок: "012.00.00", "029.11.01"
RE_COMPONENT_FOLDER = re.compile(r'^\d{3}\.\d{2}\.\d{2}$')

# Ключевые слова спецфайлов верхнего уровня → special_type
ROOT_SPECIAL_KEYWORDS = {
    'лрви': 'lrvi',
    'лри': 'lri',
    'пдс': 'pds',
    'ппс': 'pps',
    'содержание': 'contents',
}


def _is_junk_file(filename: str) -> bool:
    """Проверяет, является ли файл временным/мусорным."""
    if filename.startswith('~$') or filename.startswith('~WRL'):
        return True
    if filename.lower() in ('thumbs.db', 'desktop.ini'):
        return True
    if filename.endswith('.tmp'):
        return True
    return False


# ---------------------------------------------------------------------------
# Извлечение заголовков из документов Word
# ---------------------------------------------------------------------------

# Строки, которые не являются содержательными заголовками
_SKIP_PARAGRAPHS = {
    'су-57', 'руководство по технической эксплуатации',
    'руководство по техническому обслуживанию',
}


def _clean_title(text: str) -> str:
    """Очистка и нормализация заголовка."""
    text = text.strip()
    # Убрать управляющие символы Word
    text = text.replace('\r', '').replace('\x07', '').replace('\x0b', ' ')
    # Нормализовать тире
    text = text.replace('\u2212', '\u2013').replace('\u2012', '\u2013')
    # Убрать лишние пробелы
    text = re.sub(r'\s+', ' ', text).strip()
    # Title Case если ALL CAPS (больше 5 символов и все заглавные)
    if len(text) > 5 and text == text.upper() and any(c.isalpha() for c in text):
        # Первое слово с заглавной, остальные со строчной
        words = text.split()
        text = ' '.join(w.capitalize() if w.isalpha() else w for w in words)
    # Убрать завершающую точку
    text = text.rstrip('.')
    return text


def extract_titles_from_documents(docs: List[RawDocument]) -> Dict[str, int]:
    """Извлекает заголовки из Word-документов для файлов с пустым title_text.

    Запускает отдельный subprocess для изоляции Word COM от Flask-процесса.
    Возвращает статистику: {total, extracted, failed, skipped, failed_files, word_restarts}.
    """
    import json
    import subprocess

    stats = {'total': 0, 'extracted': 0, 'failed': 0, 'skipped': 0,
             'failed_files': [], 'word_restarts': 0}

    need_title = [d for d in docs
                  if not d.title_text
                  and d.doc_type in ('description', 'tk', 'special')
                  and (d.filepath.endswith('.doc') or d.filepath.endswith('.docx'))]

    non_word = [d for d in docs
                if not d.title_text
                and d.doc_type in ('description', 'tk', 'special')
                and not (d.filepath.endswith('.doc') or d.filepath.endswith('.docx'))]
    stats['skipped'] = len(non_word)
    stats['total'] = len(need_title) + len(non_word)

    if not need_title:
        return stats

    # Формируем вход для воркера
    worker_input = [{'filepath': d.filepath, 'doc_type': d.doc_type}
                    for d in need_title]

    # Путь к воркеру — рядом с этим файлом
    worker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               '_extract_titles_worker.py')

    try:
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'

        result = subprocess.run(
            [sys.executable, worker_path],
            input=json.dumps(worker_input, ensure_ascii=False).encode('utf-8'),
            capture_output=True, timeout=600,
            env=env,
        )

        stdout_text = result.stdout.decode('utf-8', errors='replace')
        stderr_text = result.stderr.decode('utf-8', errors='replace')

        if result.returncode != 0:
            stats['failed'] = len(need_title)
            stats['failed_files'].append({
                'file': '(subprocess)',
                'error': f'exit code {result.returncode}: {stderr_text[:500]}'
            })
            return stats

        output = json.loads(stdout_text)
        title_map = output.get('results', {})
        worker_errors = output.get('errors', [])
        stats['word_restarts'] = output.get('word_restarts', 0)

        # Заполняем title_text
        for d in need_title:
            title = title_map.get(d.filepath, '')
            if title:
                d.title_text = title
                stats['extracted'] += 1
            else:
                stats['failed'] += 1
                # Ищем ошибку для этого файла
                err_msg = 'заголовок не найден'
                for e in worker_errors:
                    if e.get('file') == d.filename:
                        err_msg = e.get('error', err_msg)
                        break
                stats['failed_files'].append({
                    'file': d.filename,
                    'error': err_msg
                })

    except subprocess.TimeoutExpired:
        stats['failed'] = len(need_title)
        stats['failed_files'].append({
            'file': '(все файлы)',
            'error': 'Timeout: воркер не завершился за 10 минут'
        })
    except Exception as e:
        stats['failed'] = len(need_title)
        stats['failed_files'].append({
            'file': '(subprocess)',
            'error': str(e)
        })

    return stats


def _extract_single_title(word, filepath: str, doc_type: str) -> Optional[str]:
    """Извлекает заголовок из одного документа.

    Возвращает: строку (заголовок или ''), None при ошибке (сигнал для retry).
    Текст ошибки сохраняется в _extract_single_title.last_error.
    """
    _extract_single_title.last_error = ''
    abs_path = os.path.abspath(filepath)

    doc = None
    try:
        doc = word.Documents.Open(abs_path, ReadOnly=True, AddToRecentFiles=False)

        # Для ТК: ищем «Наименование работы» в Shape TextFrames
        if doc_type == 'tk':
            title = _extract_tk_title_from_shapes(doc)
            if title:
                return _clean_title(title)

        # Для всех типов: первый содержательный параграф
        title = _extract_first_paragraph(doc)
        if title:
            return _clean_title(title)

        return ''
    except Exception as e:
        err_str = str(e)
        _extract_single_title.last_error = err_str
        is_rpc = 'RPC' in err_str or '-2147023174' in err_str or 'Call was rejected' in err_str
        print(f"  {'[RPC] ' if is_rpc else ''}Не удалось прочитать {os.path.basename(filepath)}: {err_str}")
        return None if is_rpc else ''
    finally:
        if doc:
            try:
                doc.Close(False)
            except Exception:
                pass


def _extract_tk_title_from_shapes(doc) -> str:
    """Ищет «Наименование работы» в Shape TextFrames документа."""
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


def _extract_first_paragraph(doc) -> str:
    """Извлекает первый содержательный параграф документа."""
    for i in range(1, min(15, doc.Paragraphs.Count + 1)):
        try:
            text = doc.Paragraphs(i).Range.Text.strip()
            if not text or len(text) < 4:
                continue
            # Пропускаем шаблонные строки колонтитулов
            if text.lower().rstrip('.') in _SKIP_PARAGRAPHS:
                continue
            # Пропускаем строки, начинающиеся с номера пункта (типа «1.», «2.»)
            if re.match(r'^\d+\.?\s', text):
                continue
            return text
        except Exception:
            continue
    return ''


def scan_raw_folder(input_dir: str) -> List[RawDocument]:
    """Сканирует сырую папку и возвращает список распознанных документов."""
    docs = []

    # Находим подпапки с описаниями и технологией
    desc_dir = None
    tech_dir = None
    graphics_dir = None
    component_dirs = []  # компонентные папки (NNN.NN.NN)

    for entry in os.listdir(input_dir):
        full = os.path.join(input_dir, entry)
        if not os.path.isdir(full):
            continue
        lower = entry.lower()
        # Рисунки проверяем РАНЬШЕ описаний, т.к. "Рисунки описание" содержит оба слова
        if 'рисунк' in lower:
            graphics_dir = full
        elif 'описание' in lower or 'описани' in lower:
            desc_dir = full
        elif 'технолог' in lower:
            tech_dir = full
        elif RE_COMPONENT_FOLDER.match(entry):
            component_dirs.append((entry, full))

    is_type_organized = bool(desc_dir or tech_dir or graphics_dir)

    # Парсим описания
    if desc_dir:
        for fname in os.listdir(desc_dir):
            fpath = os.path.join(desc_dir, fname)
            if not os.path.isfile(fpath):
                continue
            # Пропускаем временные файлы Word
            if fname.startswith('~$'):
                continue

            # ПИУН — особый файл
            if 'ПИУН' in fname and not re.search(r'рис', fname, re.IGNORECASE):
                ext_match = re.search(r'\.(docx?)$', fname, re.IGNORECASE)
                if ext_match:
                    docs.append(RawDocument(
                        filepath=fpath, filename=fname,
                        system_code='029', subsystem_code='00', component_code='00',
                        doc_type='piun', title_text='ПИУН',
                        special_type='piun'
                    ))
                continue

            m = RE_DESCRIPTION.match(fname)
            if m:
                docs.append(RawDocument(
                    filepath=fpath, filename=fname,
                    system_code=m.group(1),
                    subsystem_code=m.group(2),
                    component_code=m.group(3),
                    doc_type='description',
                    title_text=m.group(4).strip()
                ))

    # Парсим технологические карты
    if tech_dir:
        for fname in os.listdir(tech_dir):
            fpath = os.path.join(tech_dir, fname)
            if not os.path.isfile(fpath):
                continue
            if fname.startswith('~$'):
                continue

            # ТК ТО — особый файл
            if re.match(r'^\d{3}\.\d{2}\.\d{2}\s+ТК\s+ТО\b', fname, re.IGNORECASE):
                ext_match = re.search(r'\.(docx?)$', fname, re.IGNORECASE)
                if ext_match:
                    sys_match = re.match(r'^(\d{3})\.(\d{2})\.(\d{2})', fname)
                    docs.append(RawDocument(
                        filepath=fpath, filename=fname,
                        system_code=sys_match.group(1),
                        subsystem_code=sys_match.group(2),
                        component_code=sys_match.group(3),
                        doc_type='tk_to',
                        title_text='ТК ТО',
                        special_type='tk_to'
                    ))
                continue

            m = RE_TK.match(fname)
            if m:
                docs.append(RawDocument(
                    filepath=fpath, filename=fname,
                    system_code=m.group(1),
                    subsystem_code=m.group(2),
                    component_code=m.group(3),
                    doc_type='tk',
                    tk_number=int(m.group(4)),
                    title_text=m.group(5).strip()
                ))

    # --- Компонентный режим (папки NNN.NN.NN вместо Описания/Технология/Рисунки) ---
    if not is_type_organized and component_dirs:
        for folder_name, folder_path in sorted(component_dirs):
            for fname in os.listdir(folder_path):
                fpath = os.path.join(folder_path, fname)

                # Вложенная папка Рисунки внутри компонента
                if os.path.isdir(fpath):
                    if 'рисунк' in fname.lower():
                        for gfname in os.listdir(fpath):
                            gfpath = os.path.join(fpath, gfname)
                            if not os.path.isfile(gfpath) or _is_junk_file(gfname):
                                continue
                            m = RE_PIUN_GRAPHIC.match(gfname)
                            if m:
                                docs.append(RawDocument(
                                    filepath=gfpath, filename=gfname,
                                    system_code=m.group(1),
                                    subsystem_code=m.group(2),
                                    component_code=m.group(3),
                                    doc_type='graphic',
                                    title_text=f'ПИУН рис {m.group(4)}',
                                    special_type='piun_graphic'
                                ))
                                continue
                            m = RE_GRAPHIC.match(gfname)
                            if m:
                                sys_code = m.group(1)
                                if len(sys_code) == 2:
                                    sys_code = '0' + sys_code
                                docs.append(RawDocument(
                                    filepath=gfpath, filename=gfname,
                                    system_code=sys_code,
                                    subsystem_code=m.group(2),
                                    component_code=m.group(3),
                                    doc_type='graphic',
                                    title_text=f'рисунок {m.group(4)} {m.group(5).strip()}'
                                ))
                    continue

                if not os.path.isfile(fpath) or _is_junk_file(fname):
                    continue

                # ТК ТО
                if re.match(r'^\d{3}[.\-]\d{2}[.\-]\d{2}\s+ТК\s+ТО\b', fname, re.IGNORECASE):
                    ext_match = re.search(r'\.(docx?|pdf)$', fname, re.IGNORECASE)
                    if ext_match:
                        sys_match = re.match(r'^(\d{3})[.\-](\d{2})[.\-](\d{2})', fname)
                        docs.append(RawDocument(
                            filepath=fpath, filename=fname,
                            system_code=sys_match.group(1),
                            subsystem_code=sys_match.group(2),
                            component_code=sys_match.group(3),
                            doc_type='tk_to',
                            title_text='ТК ТО',
                            special_type='tk_to'
                        ))
                    continue

                # ПИУН (не рисунок)
                if 'ПИУН' in fname and not re.search(r'рис', fname, re.IGNORECASE):
                    ext_match = re.search(r'\.(docx?|pdf)$', fname, re.IGNORECASE)
                    if ext_match:
                        sys_match = re.match(r'^(\d{3})[.\-](\d{2})[.\-](\d{2})', fname)
                        sc = sys_match.group(1) if sys_match else folder_name[:3]
                        ss = sys_match.group(2) if sys_match else folder_name[4:6]
                        cc = sys_match.group(3) if sys_match else folder_name[7:9]
                        docs.append(RawDocument(
                            filepath=fpath, filename=fname,
                            system_code=sc, subsystem_code=ss, component_code=cc,
                            doc_type='piun', title_text='ПИУН',
                            special_type='piun'
                        ))
                    continue

                # Таблица
                m = RE_TABLE.match(fname)
                if m:
                    docs.append(RawDocument(
                        filepath=fpath, filename=fname,
                        system_code=m.group(1),
                        subsystem_code=m.group(2),
                        component_code=m.group(3),
                        doc_type='special',
                        title_text='',  # извлекается из содержимого документа
                        special_type='table'
                    ))
                    continue

                # ТК (технологическая карта)
                m = RE_TK.match(fname)
                if m:
                    docs.append(RawDocument(
                        filepath=fpath, filename=fname,
                        system_code=m.group(1),
                        subsystem_code=m.group(2),
                        component_code=m.group(3),
                        doc_type='tk',
                        tk_number=int(m.group(4)),
                        title_text=m.group(5).strip()
                    ))
                    continue

                # Описание с ключевым словом
                m = RE_DESCRIPTION.match(fname)
                if m:
                    docs.append(RawDocument(
                        filepath=fpath, filename=fname,
                        system_code=m.group(1),
                        subsystem_code=m.group(2),
                        component_code=m.group(3),
                        doc_type='description',
                        title_text=m.group(4).strip()
                    ))
                    continue

                # Описание без ключевого слова (только код: "012-00-00.doc")
                m = RE_PLAIN_DESCRIPTION.match(fname)
                if m:
                    docs.append(RawDocument(
                        filepath=fpath, filename=fname,
                        system_code=m.group(1),
                        subsystem_code=m.group(2),
                        component_code=m.group(3),
                        doc_type='description',
                        title_text=''
                    ))
                    continue

    # Парсим спецфайлы верхнего уровня
    for fname in os.listdir(input_dir):
        fpath = os.path.join(input_dir, fname)
        if not os.path.isfile(fpath):
            continue
        if _is_junk_file(fname):
            continue
        lower = fname.lower()

        # Перечень сокращений
        if 'перечень' in lower and 'сокращен' in lower:
            sys_match = re.match(r'^(\d{3})[.\-](\d{2})[.\-](\d{2})', fname)
            if sys_match:
                docs.append(RawDocument(
                    filepath=fpath, filename=fname,
                    system_code=sys_match.group(1),
                    subsystem_code=sys_match.group(2),
                    component_code=sys_match.group(3),
                    doc_type='special',
                    title_text='Перечень принятых сокращений',
                    special_type='abbreviations'
                ))
            continue

        # Прочие спецфайлы верхнего уровня (ЛРВИ, ЛРИ, ПДС, ППС, Содержание)
        sys_match = re.match(r'^(\d{3})[.\-](\d{2})[.\-](\d{2})\s+', fname)
        if not sys_match:
            continue
        ext_match = re.search(r'\.(docx?|pdf)$', fname, re.IGNORECASE)
        if not ext_match:
            continue
        for keyword, stype in ROOT_SPECIAL_KEYWORDS.items():
            if keyword in lower:
                title = fname[sys_match.end():].rsplit('.', 1)[0].strip()
                docs.append(RawDocument(
                    filepath=fpath, filename=fname,
                    system_code=sys_match.group(1),
                    subsystem_code=sys_match.group(2),
                    component_code=sys_match.group(3),
                    doc_type='special',
                    title_text=title,
                    special_type=stype
                ))
                break

    # Парсим рисунки
    if graphics_dir:
        for fname in os.listdir(graphics_dir):
            fpath = os.path.join(graphics_dir, fname)
            if not os.path.isfile(fpath):
                continue

            # ПИУН рисунки
            m = RE_PIUN_GRAPHIC.match(fname)
            if m:
                docs.append(RawDocument(
                    filepath=fpath, filename=fname,
                    system_code=m.group(1),
                    subsystem_code=m.group(2),
                    component_code=m.group(3),
                    doc_type='graphic',
                    title_text=f'ПИУН рис {m.group(4)}',
                    special_type='piun_graphic'
                ))
                continue

            m = RE_GRAPHIC.match(fname)
            if m:
                sys_code = m.group(1)
                if len(sys_code) == 2:
                    sys_code = '0' + sys_code
                docs.append(RawDocument(
                    filepath=fpath, filename=fname,
                    system_code=sys_code,
                    subsystem_code=m.group(2),
                    component_code=m.group(3),
                    doc_type='graphic',
                    title_text=f'рисунок {m.group(4)} {m.group(5).strip()}'
                ))

    # Извлекаем заголовки из документов, у которых title_text пустой
    title_stats = extract_titles_from_documents(docs)
    scan_raw_folder.last_title_stats = title_stats

    return docs


# ---------------------------------------------------------------------------
# Этап 2: Реестр компонентов
# ---------------------------------------------------------------------------

def get_component_name(system_code: str, subsystem: str, component: str,
                       docs: List[RawDocument]) -> str:
    """Определяет полное название компонента."""
    key = (subsystem, component)
    if system_code == '029' and key in COMPONENT_NAMES_029:
        return COMPONENT_NAMES_029[key]

    # Fallback: из описания (сохраняем оригинальный регистр)
    for d in docs:
        if (d.subsystem_code == subsystem and d.component_code == component
                and d.doc_type == 'description' and d.title_text):
            return d.title_text

    if subsystem == '00' and component == '00':
        return 'Общие сведения'
    return f'Компонент {subsystem}-{component}'


def build_component_registry(docs: List[RawDocument]) -> Dict[Tuple[str, str, str], List[RawDocument]]:
    """Группирует документы по (systemCode, subsystem, component)."""
    registry = defaultdict(list)
    for d in docs:
        key = (d.system_code, d.subsystem_code, d.component_code)
        registry[key].append(d)
    return dict(registry)


# ---------------------------------------------------------------------------
# Этап 3: Назначение info-кодов
# ---------------------------------------------------------------------------

def match_info_code(title: str) -> Optional[Tuple[str, str]]:
    """Определяет info-код по ключевым словам в заголовке."""
    title_lower = title.lower()
    best_match = None
    best_priority = -1

    for required, excluded, code, variant, priority in INFO_CODE_RULES:
        # Проверяем исключения
        if any(kw in title_lower for kw in excluded):
            continue
        # Проверяем обязательные ключевые слова
        if all(kw in title_lower for kw in required):
            if priority > best_priority:
                best_match = (code, variant)
                best_priority = priority

    return best_match


def apply_override(system_code: str, subsystem: str, component: str,
                   info_code: str) -> str:
    """Применяет таблицу overrides к info-коду."""
    # Точное совпадение
    key = (system_code, subsystem, component, info_code)
    if key in OVERRIDES:
        return OVERRIDES[key]
    # Wildcard по компоненту
    key_wild = (system_code, subsystem, '*', info_code)
    if key_wild in OVERRIDES:
        return OVERRIDES[key_wild]
    return info_code


def build_data_modules(docs: List[RawDocument],
                       model_ident: str = DEFAULT_MODEL_IDENT) -> List[Component]:
    """Строит полный список компонентов с модулями данных."""
    registry = build_component_registry(docs)
    components: List[Component] = []

    # Сортируем ключи для детерминированного порядка
    for key in sorted(registry.keys()):
        sys_code, subsys, comp = key
        # Сортируем: описания первыми (для корректных info-variant)
        comp_docs = sorted(registry[key],
                           key=lambda d: (d.doc_type != 'description', d.filename))
        comp_name = get_component_name(sys_code, subsys, comp, comp_docs)

        component = Component(
            system_code=sys_code,
            subsystem_code=subsys,
            component_code=comp,
            name=comp_name
        )

        for d in comp_docs:
            if d.doc_type == 'description':
                info_code = '040'
                info_code = apply_override(sys_code, subsys, comp, info_code)
                info_variant = 'A'
                # info_name: добавлять «Описание...» только если название
                # компонента — просто имя агрегата, а не описание содержания
                if _title_is_self_describing(comp_name):
                    info_name = ''
                elif comp == '00':
                    info_name = 'Описание и принцип действия'
                elif d.title_text:
                    info_name = INFO_NAMES.get(info_code, 'Описание устройства и принципа действия')
                else:
                    info_name = 'Описательный модуль данных'
                dm = DataModule(
                    system_code=sys_code,
                    subsystem_code=subsys,
                    component_code=comp,
                    assy_code='00',
                    disassy_code='00',
                    info_code=info_code,
                    info_variant=info_variant,
                    component_name=comp_name,
                    info_name=info_name,
                    source_files=[d.filepath]
                )
                component.data_modules.append(dm)

            elif d.doc_type == 'tk':
                result = match_info_code(d.title_text)
                if result:
                    info_code, info_variant = result
                else:
                    print(f"  ВНИМАНИЕ: не удалось определить info-код для ТК: {d.filename}")
                    info_code, info_variant = '999', 'A'

                info_code = apply_override(sys_code, subsys, comp, info_code)

                # Определяем assyCode
                assy_code = '00'
                if 'фильтроэлемент' in d.title_text.lower():
                    assy_code = '01'

                # Определяем info-name и component_name для ТК
                _is_generic_comp = comp_name.startswith('Компонент ')
                if not d.title_text:
                    info_name = 'Процедурный модуль данных'
                elif info_code in ('920', '922'):
                    info_name = 'Демонтаж и монтаж'
                else:
                    info_name = d.title_text

                # Для ТК с generic comp_name — используем заголовок ТК
                # как component_name, а info_name оставляем пустым
                if _is_generic_comp and d.title_text:
                    tk_component_name = d.title_text
                    tk_info_name = ''
                else:
                    tk_component_name = comp_name if assy_code == '00' else _filter_element_name(comp_name)
                    tk_info_name = info_name

                dm = DataModule(
                    system_code=sys_code,
                    subsystem_code=subsys,
                    component_code=comp,
                    assy_code=assy_code,
                    disassy_code='00',
                    info_code=info_code,
                    info_variant=info_variant,
                    component_name=tk_component_name,
                    info_name=tk_info_name,
                    source_files=[d.filepath]
                )
                component.data_modules.append(dm)

            elif d.doc_type == 'special' and d.special_type == 'table':
                # Таблица — info-name из заголовка документа
                table_title = d.title_text if d.title_text else d.filename.rsplit('.', 1)[0]
                dm = DataModule(
                    system_code=sys_code,
                    subsystem_code=subsys,
                    component_code=comp,
                    assy_code='00',
                    disassy_code='00',
                    info_code='040',
                    info_variant=chr(ord('A') + len([
                        m for m in component.data_modules
                        if m.info_code == '040'
                    ])),
                    component_name=table_title,
                    info_name='',
                    source_files=[d.filepath]
                )
                component.data_modules.append(dm)

            elif d.doc_type == 'special' and d.special_type == 'abbreviations':
                dm = DataModule(
                    system_code=sys_code,
                    subsystem_code=subsys,
                    component_code=comp,
                    assy_code='00',
                    disassy_code='00',
                    info_code='005',
                    info_variant='A',
                    component_name=comp_name,
                    info_name='Перечень принятых сокращений',
                    source_files=[d.filepath]
                )
                component.data_modules.append(dm)

            elif d.doc_type == 'tk_to':
                # Разбиение ТК ТО на 3 модуля
                for ic, iv, iname in TK_TO_MODULES:
                    dm = DataModule(
                        system_code=sys_code,
                        subsystem_code=subsys,
                        component_code=comp,
                        assy_code='00',
                        disassy_code='00',
                        info_code=ic,
                        info_variant=iv,
                        component_name=comp_name,
                        info_name=iname,
                        source_files=[d.filepath]
                    )
                    component.data_modules.append(dm)

            elif d.doc_type == 'piun':
                # Разбиение ПИУН на 5 модулей
                for dc, pname, iname in PIUN_MODULES:
                    dm = DataModule(
                        system_code=sys_code,
                        subsystem_code=subsys,
                        component_code=comp,
                        assy_code='00',
                        disassy_code=dc,
                        info_code='420',
                        info_variant='A',
                        component_name=pname,
                        info_name=iname,
                        source_files=[d.filepath]
                    )
                    component.data_modules.append(dm)

        # Привязка рисунков ПИУН к соответствующим DM
        piun_graphics = [d for d in comp_docs
                         if d.doc_type == 'graphic' and d.special_type == 'piun_graphic']
        for pg in piun_graphics:
            # Извлекаем номер рисунка (101-105)
            m = re.search(r'рис\s*(\d+)', pg.title_text)
            if m:
                pic_num = int(m.group(1))
                # 101 → disassy_code 01, 102 → 02, ...
                dc = f'{pic_num - 100:02d}'
                for dm in component.data_modules:
                    if dm.info_code == '420' and dm.disassy_code == dc:
                        dm.source_files.append(pg.filepath)
                        break

        # Привязка обычных рисунков к описаниям
        regular_graphics = [d for d in comp_docs
                            if d.doc_type == 'graphic' and d.special_type != 'piun_graphic']
        desc_modules = [dm for dm in component.data_modules if dm.info_code in ('040', '042')]
        if desc_modules and regular_graphics:
            for g in regular_graphics:
                # Рисунки привязываем к описанию того же компонента
                desc_modules[0].source_files.append(g.filepath)

        # Сортируем модули по info-коду для единообразного порядка
        component.data_modules.sort(key=lambda dm: (dm.assy_code, dm.disassy_code, dm.info_code))

        # Дедупликация DMC-кодов: инкремент info_variant при совпадении
        seen_keys: Dict[str, int] = {}
        for dm in component.data_modules:
            key = (dm.assy_code, dm.disassy_code, dm.info_code, dm.info_variant)
            if key in seen_keys:
                seen_keys[key] += 1
                # A→B, B→C, ...
                dm.info_variant = chr(ord('A') + seen_keys[key])
            else:
                seen_keys[key] = 0

        # Убираем дублирование: если info_name слишком похож на comp_name
        from difflib import SequenceMatcher
        for dm in component.data_modules:
            if dm.info_name and dm.component_name:
                ratio = SequenceMatcher(
                    None, dm.component_name.lower(), dm.info_name.lower()
                ).ratio()
                if ratio > 0.75:
                    dm.info_name = ''

        components.append(component)

    return components


# Корни слов, указывающие что название уже описывает содержание модуля
_SELF_DESCRIBING_ROOTS = (
    'указани', 'осмотр', 'смазк', 'заправк', 'слив', 'обслуживан',
    'консервац', 'расконсервац', 'демонтаж', 'монтаж', 'работ',
    'таблиц', 'очистк', 'зарядк', 'контрол', 'проверк', 'особенност',
    'внеплановое', 'подготовительн', 'заключительн',
)


def _title_is_self_describing(title: str) -> bool:
    """Проверяет, описывает ли название само содержание модуля данных.

    Если да — не нужно добавлять «Описание и принцип действия».
    """
    if not title:
        return False
    lower = title.lower()
    return any(root in lower for root in _SELF_DESCRIBING_ROOTS)


def _filter_element_name(comp_name: str) -> str:
    """Генерирует имя для фильтроэлемента, сохраняя оригинальный регистр."""
    return f'Фильтроэлемент {comp_name}'


# ---------------------------------------------------------------------------
# Этап 4: Создание папок и копирование файлов
# ---------------------------------------------------------------------------

def build_dmc_string(dm: DataModule, model_ident: str = DEFAULT_MODEL_IDENT,
                     system_diff: str = DEFAULT_SYSTEM_DIFF,
                     item_location: str = DEFAULT_ITEM_LOCATION) -> str:
    """Строит DMC-строку в формате S1000D: S5-A-029-11-01-00A-040A-A.

    Формат: model-diff-sys-subSys-comp-assyDisassyVariant-infoVariant-loc
    """
    # assy/disassy — объединённое 2-значное поле
    ad_code = dm.disassy_code if dm.disassy_code != '00' else dm.assy_code
    return (f"{model_ident}-{system_diff}-{dm.system_code}-"
            f"{dm.subsystem_code}-{dm.component_code}-"
            f"{ad_code}A-"
            f"{dm.info_code}{dm.info_variant}-{item_location}")


def create_folder_structure(components: List[Component], output_dir: str,
                            model_ident: str = DEFAULT_MODEL_IDENT,
                            system_diff: str = DEFAULT_SYSTEM_DIFF) -> Dict[str, str]:
    """Создаёт структуру папок и копирует файлы. Возвращает mapping DMC → путь папки.

    Структура папок:
    - 3-уровневая с группировкой по подсистемам, если в подсистеме >1 компонента
    - 2-уровневая (плоская) для подсистем с единственным компонентом и для 00-00
    """
    os.makedirs(_long_path(output_dir), exist_ok=True)
    created = {}

    # Группируем компоненты по подсистемам
    subsystem_groups: Dict[str, List[Component]] = defaultdict(list)
    for comp in components:
        subsys_key = f"{comp.system_code}-{comp.subsystem_code}"
        subsystem_groups[subsys_key].append(comp)

    for subsys_key in sorted(subsystem_groups.keys()):
        group = subsystem_groups[subsys_key]
        sys_code = group[0].system_code
        subsys_code = group[0].subsystem_code

        # Определяем: нужна ли промежуточная папка подсистемы
        # НЕ нужна, если: подсистема 00 (общесистемный) или в группе один компонент
        need_subsystem_folder = subsys_code != '00' and len(group) > 1

        if need_subsystem_folder:
            # Название подсистемы берём из компонента 00 (если есть)
            subsys_name = None
            for c in group:
                if c.component_code == '00':
                    subsys_name = c.name
                    break
            if not subsys_name:
                subsys_name = f'Подсистема {subsys_code}'

            subsys_folder = sanitize(f"{sys_code}-{subsys_code} - {subsys_name}")
            subsys_path = os.path.join(output_dir, subsys_folder)
            os.makedirs(_long_path(subsys_path), exist_ok=True)

            for comp in group:
                comp_path = _create_component_folder(
                    comp, subsys_path, model_ident, system_diff, created)
        else:
            for comp in group:
                comp_path = _create_component_folder(
                    comp, output_dir, model_ident, system_diff, created)

    return created


def _create_component_folder(comp: Component, parent_dir: str,
                             model_ident: str, system_diff: str,
                             created: Dict[str, str]) -> str:
    """Создаёт папку компонента с вложенными папками модулей данных."""
    display_name = comp.name
    if comp.component_code == '00' and comp.subsystem_code == '00':
        # Добавляем "Общие сведения" только если name — generic fallback
        if comp.name == 'Общие сведения':
            display_name = 'Общие сведения'
        else:
            display_name = comp.name

    l1_name = f"{comp.system_code}-{comp.subsystem_code}-{comp.component_code} - {display_name}"
    l1_name = sanitize(l1_name)
    l1_path = os.path.join(parent_dir, l1_name)
    os.makedirs(_long_path(l1_path), exist_ok=True)

    for dm in comp.data_modules:
        dmc = build_dmc_string(dm, model_ident, system_diff)
        if dm.info_name:
            l2_name = f"[{dmc}] {dm.component_name}. {dm.info_name}"
        else:
            l2_name = f"[{dmc}] {dm.component_name}"
        l2_name = sanitize(l2_name)
        l2_path = os.path.join(l1_path, l2_name)
        os.makedirs(_long_path(l2_path), exist_ok=True)
        created[dmc] = l2_path

        for src in dm.source_files:
            if os.path.isfile(_long_path(src)):
                dst = os.path.join(l2_path, os.path.basename(src))
                if not os.path.exists(_long_path(dst)):
                    shutil.copy2(_long_path(src), _long_path(dst))
                # Ищем парный .docx для .doc
                if src.endswith('.doc') and not src.endswith('.docx'):
                    docx_pair = src + 'x'
                    if os.path.isfile(_long_path(docx_pair)):
                        dst2 = os.path.join(l2_path, os.path.basename(docx_pair))
                        if not os.path.exists(_long_path(dst2)):
                            shutil.copy2(_long_path(docx_pair), _long_path(dst2))

    return l1_path


# ---------------------------------------------------------------------------
# Валидация
# ---------------------------------------------------------------------------

def extract_dmc_from_folder(folder_name: str) -> Optional[str]:
    """Извлекает DMC-код из имени папки [S5-A-029-11-01-00A-040A-A]."""
    m = re.search(r'\[([A-Z0-9]+-[A-Z]-\d{2,3}-\d{2}-\d{2}-\d{2}[A-Z]-\d{3}[A-Z]-[A-Z])\]', folder_name)
    if m:
        return m.group(1)
    return None


def _normalize_name(name: str) -> str:
    """Нормализует имя папки для нечёткого сравнения."""
    name = name.strip().lower()
    name = re.sub(r'\s+', ' ', name)
    name = name.rstrip('.')
    return name


def _extract_l1_name(folder: str) -> str:
    """Извлекает название компонента из L1 папки: '029-11-01 - Гидрокомпенсатор' → 'Гидрокомпенсатор'."""
    parts = folder.split(' - ', 1)
    return parts[1].strip() if len(parts) == 2 else ''


def _extract_l2_title(folder: str) -> str:
    """Извлекает title из L2 папки: '[S5-...] Компонент. Описание' → 'Компонент. Описание'."""
    m = re.search(r'\]\s*(.+)$', folder)
    return m.group(1).strip() if m else ''


def _names_match(name1: str, name2: str, threshold: float = 0.85) -> Tuple[bool, float]:
    """Нечёткое сравнение имён. Возвращает (совпадает, score)."""
    n1 = _normalize_name(name1)
    n2 = _normalize_name(name2)
    if not n1 or not n2:
        return (True, 1.0) if n1 == n2 else (False, 0.0)
    if n1 == n2:
        return True, 1.0
    # Prefix match (для усечённых Windows MAX_PATH имён)
    shorter, longer = (n1, n2) if len(n1) <= len(n2) else (n2, n1)
    if len(shorter) >= 15 and longer.startswith(shorter):
        return True, 1.0
    score = difflib.SequenceMatcher(None, n1, n2).ratio()
    return score >= threshold, score


def validate_against_reference(output_dir: str, reference_dir: str,
                                silent: bool = False) -> Dict:
    """Сравнивает сгенерированную структуру с эталонной.

    Возвращает структурированный результат (dict) для программного использования.
    При silent=False также печатает отчёт в stdout.
    """
    def log(msg=''):
        if not silent:
            print(msg)

    log("\n" + "=" * 70)
    log("ВАЛИДАЦИЯ")
    log("=" * 70)

    # Собираем данные из reference
    ref_dmcs = {}      # DMC → полное имя L2 папки
    ref_l1_folders = set()
    for l1 in os.listdir(reference_dir):
        l1_path = os.path.join(reference_dir, l1)
        if not os.path.isdir(l1_path):
            continue
        ref_l1_folders.add(l1)
        for l2 in os.listdir(l1_path):
            if not os.path.isdir(os.path.join(l1_path, l2)):
                continue
            dmc = extract_dmc_from_folder(l2)
            if dmc:
                ref_dmcs[dmc] = l2

    # Собираем данные из output
    out_dmcs = {}      # DMC → полное имя L2 папки
    out_l1_folders = set()
    for l1 in os.listdir(output_dir):
        l1_path = os.path.join(output_dir, l1)
        if not os.path.isdir(l1_path):
            continue
        out_l1_folders.add(l1)
        for l2 in os.listdir(l1_path):
            if not os.path.isdir(os.path.join(l1_path, l2)):
                continue
            dmc = extract_dmc_from_folder(l2)
            if dmc:
                out_dmcs[dmc] = l2

    result = {
        'l1_ref_count': len(ref_l1_folders),
        'l1_out_count': len(out_l1_folders),
        'l2_ref_count': len(ref_dmcs),
        'l2_out_count': len(out_dmcs),
    }

    # --- Level 1: коды и имена ---
    ref_l1_norm = {f.split(' - ')[0].strip(): f for f in ref_l1_folders}
    out_l1_norm = {f.split(' - ')[0].strip(): f for f in out_l1_folders}

    l1_code_match = set(ref_l1_norm.keys()) & set(out_l1_norm.keys())
    l1_only_ref = sorted(set(ref_l1_norm.keys()) - set(out_l1_norm.keys()))
    l1_only_out = sorted(set(out_l1_norm.keys()) - set(ref_l1_norm.keys()))

    l1_name_matches = 0
    l1_name_mismatches = []
    for code in sorted(l1_code_match):
        ref_name = _extract_l1_name(ref_l1_norm[code])
        out_name = _extract_l1_name(out_l1_norm[code])
        ok, score = _names_match(ref_name, out_name)
        if ok:
            l1_name_matches += 1
        else:
            l1_name_mismatches.append({
                'code': code, 'ref': ref_name, 'gen': out_name, 'score': score
            })

    log(f"\n--- Папки Level 1 (компоненты) ---")
    log(f"  Reference: {len(ref_l1_folders)}, Generated: {len(out_l1_folders)}")
    log(f"  Коды совпали: {len(l1_code_match)}")
    log(f"  Имена совпали: {l1_name_matches}/{len(l1_code_match)}")
    if l1_only_ref:
        log(f"  Только в reference ({len(l1_only_ref)}):")
        for k in l1_only_ref:
            log(f"    - {ref_l1_norm[k]}")
    if l1_only_out:
        log(f"  Только в generated ({len(l1_only_out)}):")
        for k in l1_only_out:
            log(f"    + {out_l1_norm[k]}")
    if l1_name_mismatches:
        log(f"  Несовпадения имён ({len(l1_name_mismatches)}):")
        for m in l1_name_mismatches:
            log(f"    {m['code']}: ref=\"{m['ref']}\" gen=\"{m['gen']}\" ({m['score']:.2f})")

    result['l1_code_matched'] = len(l1_code_match)
    result['l1_only_ref'] = [ref_l1_norm[k] for k in l1_only_ref]
    result['l1_only_out'] = [out_l1_norm[k] for k in l1_only_out]
    result['l1_name_matched'] = l1_name_matches
    result['l1_name_mismatches'] = l1_name_mismatches

    # --- Level 2: DMC-коды и имена ---
    matched_dmcs = sorted(set(ref_dmcs.keys()) & set(out_dmcs.keys()))
    only_ref_dmcs = sorted(set(ref_dmcs.keys()) - set(out_dmcs.keys()))
    only_out_dmcs = sorted(set(out_dmcs.keys()) - set(ref_dmcs.keys()))

    l2_name_matches = 0
    l2_name_mismatches = []
    for dmc in matched_dmcs:
        ref_title = _extract_l2_title(ref_dmcs[dmc])
        out_title = _extract_l2_title(out_dmcs[dmc])
        ok, score = _names_match(ref_title, out_title)
        if ok:
            l2_name_matches += 1
        else:
            l2_name_mismatches.append({
                'dmc': dmc, 'ref': ref_title, 'gen': out_title, 'score': score
            })

    log(f"\n--- Папки Level 2 (модули данных) ---")
    log(f"  Reference: {len(ref_dmcs)}, Generated: {len(out_dmcs)}")
    log(f"  DMC совпали: {len(matched_dmcs)}")
    log(f"  Имена совпали: {l2_name_matches}/{len(matched_dmcs)}")
    if only_ref_dmcs:
        log(f"  Только в reference ({len(only_ref_dmcs)}):")
        for dmc in only_ref_dmcs:
            log(f"    - {dmc}")
    if only_out_dmcs:
        log(f"  Только в generated ({len(only_out_dmcs)}):")
        for dmc in only_out_dmcs:
            log(f"    + {dmc}")
    if l2_name_mismatches:
        log(f"  Несовпадения имён ({len(l2_name_mismatches)}):")
        for m in l2_name_mismatches:
            log(f"    {m['dmc']}:")
            log(f"      ref: {m['ref']}")
            log(f"      gen: {m['gen']}")
            log(f"      score: {m['score']:.2f}")

    # Итого
    total_ref = len(ref_dmcs)
    dmc_score = len(matched_dmcs) / total_ref * 100 if total_ref > 0 else 0
    log(f"\n  ИТОГО DMC: {len(matched_dmcs)}/{total_ref} ({dmc_score:.1f}%)")
    log(f"  ИТОГО имена L1: {l1_name_matches}/{len(l1_code_match)}")
    log(f"  ИТОГО имена L2: {l2_name_matches}/{len(matched_dmcs)}")

    result['l2_dmc_matched'] = len(matched_dmcs)
    result['l2_only_ref'] = only_ref_dmcs
    result['l2_only_out'] = only_out_dmcs
    result['l2_name_matched'] = l2_name_matches
    result['l2_name_mismatches'] = l2_name_mismatches
    result['dmc_score_pct'] = dmc_score

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Преобразование сырых документов в структуру S1000D')
    parser.add_argument('--input', '-i', required=True,
                        help='Путь к сырой папке (doc_source_29_raw)')
    parser.add_argument('--output', '-o', required=True,
                        help='Путь для выходной структуры')
    parser.add_argument('--validate', '-v',
                        help='Путь к эталонной папке для валидации')
    parser.add_argument('--model-ident', default=DEFAULT_MODEL_IDENT,
                        help=f'Model identification code (по умолчанию: {DEFAULT_MODEL_IDENT})')
    parser.add_argument('--system-diff', default=DEFAULT_SYSTEM_DIFF,
                        help=f'System difference code (по умолчанию: {DEFAULT_SYSTEM_DIFF})')
    parser.add_argument('--config', default='config.ini',
                        help='Путь к config.ini')

    args = parser.parse_args()

    # Читаем config если есть
    model_ident = args.model_ident
    system_diff = args.system_diff
    if os.path.isfile(args.config):
        cfg = configparser.ConfigParser()
        cfg.read(args.config, encoding='utf-8')
        if cfg.has_section('raw_import'):
            model_ident = cfg.get('raw_import', 'model_ident_code', fallback=model_ident)
            system_diff = cfg.get('raw_import', 'system_diff_code', fallback=system_diff)

    if not os.path.isdir(args.input):
        print(f"Ошибка: входная папка не найдена: {args.input}")
        return 1

    print(f"Входная папка: {args.input}")
    print(f"Выходная папка: {args.output}")
    print(f"Model: {model_ident}, SystemDiff: {system_diff}")

    # Этап 1: сканирование
    print("\n[1/4] Сканирование файлов...")
    docs = scan_raw_folder(args.input)
    desc_count = sum(1 for d in docs if d.doc_type == 'description')
    tk_count = sum(1 for d in docs if d.doc_type == 'tk')
    special_count = sum(1 for d in docs if d.doc_type in ('piun', 'tk_to', 'special'))
    graphic_count = sum(1 for d in docs if d.doc_type == 'graphic')
    print(f"  Найдено: {len(docs)} файлов "
          f"(описаний: {desc_count}, ТК: {tk_count}, "
          f"спец: {special_count}, рисунков: {graphic_count})")

    # Этап 2-3: построение компонентов и назначение info-кодов
    print("\n[2-3/4] Построение реестра компонентов и назначение info-кодов...")
    components = build_data_modules(docs, model_ident)
    total_dm = sum(len(c.data_modules) for c in components)
    print(f"  Компонентов: {len(components)}, модулей данных: {total_dm}")

    for comp in components:
        print(f"  {comp.system_code}-{comp.subsystem_code}-{comp.component_code} "
              f"{comp.name}: {len(comp.data_modules)} DM")

    # Этап 4: создание папок (с предварительной очисткой)
    print(f"\n[4/4] Создание структуры папок в {args.output}...")
    if os.path.isdir(args.output):
        shutil.rmtree(_long_path(args.output))
    created = create_folder_structure(components, args.output, model_ident, system_diff)
    print(f"  Создано папок модулей данных: {len(created)}")

    # Валидация
    if args.validate:
        validate_against_reference(args.output, args.validate)

    print("\nГотово.")
    return 0


if __name__ == '__main__':
    exit(main())
