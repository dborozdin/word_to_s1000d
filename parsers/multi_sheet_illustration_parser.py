#!/usr/bin/env python3
"""
Парсер многолистовых иллюстраций для S1000D.
Ищет паттерны вида:
1. 'Рисунок 1 (лист 1, лист 2, лист 3, лист 4)' - создает figure с 4 graphic элементами
2. 'Размещение РСУО на самолете... (лист 1, лист 2, лист 3, лист 4)' - то же самое
"""

import re
import os
import datetime
from typing import Dict, List, Any, Tuple


def find_multi_sheet_references(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Находит ссылки на многолистовые иллюстрации в тексте элементов.
    Ищет паттерны вида "рисунок X (лист 1, лист 2, ...)".
    """
    multi_sheet_refs = []

    print(f"Поиск многолистовых иллюстраций среди {len(elements)} элементов")

    for i, element in enumerate(elements):
        elem_type = element.get('type', 'unknown')
        content = element.get('content', '')

        # ИСПРАВЛЕНИЕ: проверяем все типы элементов
        if elem_type in ['paragraph', 'unnumbered_list', 'illustration_reference', 'illustration', 'numbered_paragraph_header', 'header', 'title']:
            print(f"Проверяем элемент {i} типа '{elem_type}': '{content[:60]}...'")

        # Ищем упоминания многолистовых иллюстраций
        # Используем более общий паттерн для поиска всех листов
        # Паттерн 1: "Рисунок X - текст (лист 1, лист 2, ...)"
        figure_pattern1 = r'[Рр]исунок\s*(\d+)\s*[–-]\s*(.+?)(?:\s*\(|\s*$)'
        # Паттерн 2: "Рисунок X - текст лист 1, лист 2, ..." (без скобок)
        figure_pattern2 = r'[Рр]исунок\s*(\d+)\s*[–-]\s*(.+?)(?:\s+лист\s+\d+|\s*$)'

        sheet_pattern = r'лист\s*(\d+)'

        figure_match = None
        title_part = ""

        # Пробуем первый паттерн
        figure_match = re.search(figure_pattern1, content, re.IGNORECASE | re.DOTALL)
        if figure_match:
            figure_num = int(figure_match.group(1))
            title_part = figure_match.group(2).strip()
        else:
            # Пробуем второй паттерн
            figure_match = re.search(figure_pattern2, content, re.IGNORECASE | re.DOTALL)
            if figure_match:
                figure_num = int(figure_match.group(1))
                title_part = figure_match.group(2).strip()

        if figure_match:
            # Ищем все листы в тексте
            sheet_matches = re.findall(sheet_pattern, content, re.IGNORECASE)
            sheets = [int(x) for x in sheet_matches]

            print(f"  Найден рисунок {figure_num}, листы: {sheets}")

            if len(sheets) > 1:
                # Проверяем, не добавили ли мы уже эту иллюстрацию
                already_exists = any(
                    ref['figure_number'] == figure_num for ref in multi_sheet_refs
                )

                if not already_exists:
                    multi_sheet_refs.append({
                        'figure_number': figure_num,
                        'sheet_count': len(sheets),
                        'sheets': sheets,
                        'element': element,
                        'content': content
                    })
                    print(f"  ✓ Добавлена многолистовая иллюстрация {figure_num} с листами: {sheets}")
                else:
                    print(f"  ⚠ Рисунок {figure_num} уже добавлен")
            else:
                print(f"  ✗ Рисунок {figure_num} имеет только {len(sheets)} лист(ов)")
        else:
            print(f"  ✗ Паттерн не найден")

    print(f"Всего найдено многолистовых иллюстраций: {len(multi_sheet_refs)}")
    return multi_sheet_refs


def create_multi_sheet_figure(multi_ref: Dict[str, Any], start_graphic_num: int = 0, graphic_ident_prefix: str = None) -> Dict[str, Any]:
    """
    Создает элемент многолистовой иллюстрации для S1000D.
    """
    figure_num = multi_ref['figure_number']
    sheets = multi_ref['sheets']
    element = multi_ref['element']
    effective_prefix = graphic_ident_prefix or "GS5-A-120-10-00-00A-041A-A_001_RU-RU"

    # Определяем базовое название иллюстрации
    content = multi_ref['content']

    # Извлекаем название рисунка
    title_match = re.search(r'[Рр]исунок\s*\d+\s*[–-]\s*(.+?)(?:\s*\(|$)', content, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()
    else:
        # Альтернативный паттерн
        title_match = re.search(r'[Рр]исунок\s*\d+\s*[–-]\s*(.+)', content, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
        else:
            title = f"Рисунок {figure_num}"

    # Очищаем заголовок от ссылок на листы
    title = re.sub(r'\s*\(?\s*лист\s*\d+(\s*[,\s]*лист\s*\d+)*\s*\)?', '', title, flags=re.IGNORECASE).strip()

    # Создаем ID для figure
    figure_id = f"ICN{figure_num:02d}"

    # Создаем графические элементы для каждого листа
    graphics = []
    for idx, sheet_num in enumerate(sheets):
        graphic_num = start_graphic_num + idx
        graphic_ident = f"{effective_prefix}-GRAPHIC{graphic_num}"
        
        graphics.append({
            'infoEntityIdent': graphic_ident,
            'id': f"g{figure_num}-{idx + 1}",
            'reproductionScale': "32",
            'reproductionWidth': "170mm",
            'reproductionHeight': "120mm"
        })
    
    # Создаем XML для многолистовой иллюстрации - ОДИН figure с НЕСКОЛЬКИМИ graphic
    graphic_xml_parts = []
    for graphic in graphics:
        graphic_xml_parts.append(
            f'<graphic infoEntityIdent="{graphic["infoEntityIdent"]}" '
            f'reproductionScale="{graphic["reproductionScale"]}" '
            f'reproductionWidth="{graphic["reproductionWidth"]}" '
            f'reproductionHeight="{graphic["reproductionHeight"]}" '
            f'id="{graphic["id"]}"/>'
        )
    
    figure_xml = f'<figure id="{figure_id}"><title>{title}</title>' + ''.join(graphic_xml_parts) + '</figure>'
    
    # Используем позицию из оригинального элемента
    combined_elem = {
        'type': 'illustration',
        'start_line': element.get('start_line', 0),
        'start_char': element.get('start_char', 0),
        'end_line': element.get('end_line', 0),
        'end_char': element.get('end_char', 0),
        'start_para': element.get('start_para', 0),
        'end_para': element.get('end_para', 0),
        'content': title,
        'xml_example': figure_xml,
        'details': f'Многолистовая иллюстрация {figure_num}, листов: {len(sheets)}',
        'context_text': element.get('context_text', ''),
        'figure_number': figure_num,
        'is_multi_sheet': True,
        'sheet_count': len(sheets),
        'graphics': graphics,
        'graphic_start_num': start_graphic_num
    }
    
    return combined_elem


def process_multi_sheet_illustrations(elements: List[Dict[str, Any]], graphic_ident_prefix: str = None) -> List[Dict[str, Any]]:
    """
    Обрабатывает элементы и группирует многолистовые иллюстрации.
    Заменяет группы последовательных элементов иллюстраций с одинаковым номером
    на один многолистовый элемент figure.
    """
    processed_elements = []
    i = 0

    while i < len(elements):
        element = elements[i]

        # Проверяем, не является ли это началом группы многолистовой иллюстрации
        if element.get('type') == 'illustration':
            content = element.get('content', '')
            fig_match = re.search(r'[Рр]исунок\s*(\d+)', content)

            if fig_match:
                fig_num = int(fig_match.group(1))

                # Проверяем, есть ли следующие элементы с тем же номером рисунка
                group_illustrations = [element]
                j = i + 1

                while j < len(elements) and elements[j].get('type') == 'illustration':
                    next_content = elements[j].get('content', '')
                    next_match = re.search(r'[Рр]исунок\s*(\d+)', next_content)
                    if next_match and int(next_match.group(1)) == fig_num:
                        group_illustrations.append(elements[j])
                        j += 1
                    else:
                        break

                # Если нашли группу из нескольких иллюстраций с одинаковым номером
                if len(group_illustrations) > 1:
                    print(f"Заменяем группу из {len(group_illustrations)} иллюстраций рисунка {fig_num} на многолистовую иллюстрацию")

                    # Определяем начальный номер для графических файлов на основе позиции первой иллюстрации
                    # Подсчитываем, сколько одиночных иллюстраций было до этой группы
                    graphic_start_num = sum(1 for e in elements[:i] if e.get('type') == 'illustration')

                    # Создаем многолистовую иллюстрацию
                    multi_sheet_figure = create_multi_sheet_figure_from_elements(group_illustrations, graphic_start_num, graphic_ident_prefix=graphic_ident_prefix)
                    processed_elements.append(multi_sheet_figure)

                    # Пропускаем все элементы группы
                    i = j
                    continue

        # Обычный элемент - добавляем как есть
        processed_elements.append(element)
        i += 1

    print(f"Обработано элементов: {len(processed_elements)} (было {len(elements)})")
    return processed_elements


def create_multi_sheet_figure_from_elements(illustrations: List[Dict[str, Any]], start_graphic_num: int = 0, graphic_ident_prefix: str = None) -> Dict[str, Any]:
    """
    Создает элемент многолистовой иллюстрации из группы элементов illustration.
    """
    if not illustrations:
        return None

    effective_prefix = graphic_ident_prefix or "GS5-A-120-10-00-00A-041A-A_001_RU-RU"

    # Берем первый элемент для основных данных
    first_element = illustrations[0]
    content = first_element.get('content', '')

    # Извлекаем номер рисунка и базовое название
    fig_match = re.search(r'[Рр]исунок\s*(\d+)\s*[–-]\s*(.+?)(?:\s*\(?\s*лист\s*\d+|\s*$)', content, re.IGNORECASE)
    if fig_match:
        figure_num = int(fig_match.group(1))
        title = fig_match.group(2).strip()
    else:
        # Fallback
        fig_match = re.search(r'[Рр]исунок\s*(\d+)', content)
        figure_num = int(fig_match.group(1)) if fig_match else 1
        title = f"Рисунок {figure_num}"

    # Очищаем заголовок от ссылок на листы
    title = re.sub(r'\s*\(?\s*лист\s*\d+(\s*[,\s]*лист\s*\d+)*\s*\)?', '', title, flags=re.IGNORECASE).strip()

    # Создаем ID для figure
    figure_id = f"ICN{figure_num:02d}"

    # Создаем графические элементы для каждого листа
    graphics = []
    for idx, illustration in enumerate(illustrations):
        graphic_num = start_graphic_num + idx
        graphic_ident = f"{effective_prefix}-GRAPHIC{graphic_num}"

        graphics.append({
            'infoEntityIdent': graphic_ident,
            'id': f"g{figure_num}-{idx + 1}",
            'reproductionScale': "32",
            'reproductionWidth': "170mm",
            'reproductionHeight': "120mm"
        })

    # Создаем XML для многолистовой иллюстрации
    graphic_xml_parts = []
    for graphic in graphics:
        graphic_xml_parts.append(
            f'<graphic infoEntityIdent="{graphic["infoEntityIdent"]}" '
            f'reproductionScale="{graphic["reproductionScale"]}" '
            f'reproductionWidth="{graphic["reproductionWidth"]}" '
            f'reproductionHeight="{graphic["reproductionHeight"]}" '
            f'id="{graphic["id"]}"/>'
        )

    figure_xml = f'<figure id="{figure_id}"><title>{title}</title>' + ''.join(graphic_xml_parts) + '</figure>'

    # Используем позицию из первого элемента
    combined_elem = {
        'type': 'illustration',
        'start_line': first_element.get('start_line', 0),
        'start_char': first_element.get('start_char', 0),
        'end_line': illustrations[-1].get('end_line', 0),  # До последнего элемента
        'end_char': illustrations[-1].get('end_char', 0),
        'start_para': first_element.get('start_para', 0),
        'end_para': illustrations[-1].get('end_para', 0),
        'content': title,
        'xml_example': figure_xml,
        'details': f'Многолистовая иллюстрация {figure_num}, листов: {len(illustrations)}',
        'context_text': first_element.get('context_text', ''),
        'figure_number': figure_num,
        'is_multi_sheet': True,
        'sheet_count': len(illustrations),
        'graphics': graphics,
        'graphic_start_num': start_graphic_num
    }

    return combined_elem


def generate_multi_sheet_illustration_log(document_path: str, multi_sheet_refs: List[Dict[str, Any]], output_path: str) -> str:
    """
    Генерирует лог обработки многолистовых иллюстраций.
    """
    filename = os.path.basename(document_path).replace('.docx', '').replace('.doc', '')
    log_path = os.path.join(output_path, f"multi_sheet_illustrations_{filename}.log")

    with open(log_path, 'w', encoding='utf-8') as f:
        f.write("Обработка многолистовых иллюстраций\n")
        f.write(f"Сгенерировано: {datetime.datetime.now()}\n")
        f.write(f"Исходный файл: {document_path}\n")
        f.write("=" * 80 + "\n\n")
        
        f.write(f"Найдено многолистовых иллюстраций: {len(multi_sheet_refs)}\n\n")
        
        for i, ref in enumerate(multi_sheet_refs, 1):
            f.write(f"Многолистовая иллюстрация {i}:\n")
            f.write(f"  Номер рисунка: {ref['figure_number']}\n")
            f.write(f"  Количество листов: {ref['sheet_count']}\n")
            f.write(f"  Листы: {ref['sheets']}\n")
            f.write(f"  Контент: {ref['content']}\n")
            f.write("\n")
        
        f.write("=" * 80 + "\n")
    
    print(f"Лог многолистовых иллюстраций сохранен в: {log_path}")
    return log_path
