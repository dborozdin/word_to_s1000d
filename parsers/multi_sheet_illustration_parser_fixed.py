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
    processed_elements = set()  # Track processed elements to avoid duplicates
    
    for element in elements:
        # ИСПРАВЛЕНИЕ: добавляем 'illustration_reference' в список типов
        if element.get('type') in ['paragraph', 'unnumbered_list', 'illustration_reference']:
            content = element.get('content', '')
            element_id = id(element)  # Unique identifier for this element
            
            # Skip if already processed
            if element_id in processed_elements:
                continue
                
            # Ищем упоминания многолистовых иллюстраций
            # Используем более общий паттерн для поиска всех листов
            figure_pattern = r'[Рр]исунок\s*(\d+)\s*[–-]\s*(.+?)(?:\s*\(|$)'
            sheet_pattern = r'лист\s*(\d+)'
            
            figure_match = re.search(figure_pattern, content, re.IGNORECASE | re.DOTALL)
            if figure_match:
                figure_num = int(figure_match.group(1))
                title_part = figure_match.group(2).strip()
                
                # Ищем все листы в тексте
                sheet_matches = re.findall(sheet_pattern, content, re.IGNORECASE)
                sheets = [int(x) for x in sheet_matches]
                
                if len(sheets) > 1:
                    # Проверяем, не добавили ли мы уже эту иллюстрацию
                    already_exists = any(
                        ref['figure_number'] == figure_num and ref['content'] == content 
                        for ref in multi_sheet_refs
                    )
                    
                    if not already_exists:
                        multi_sheet_refs.append({
                            'figure_number': figure_num,
                            'sheet_count': len(sheets),
                            'sheets': sheets,
                            'element': element,
                            'content': content
                        })
                        print(f"Найдена многолистовая иллюстрация {figure_num} с листами: {sheets}")
                        
                    processed_elements.add(element_id)
                    break  # Found multi-sheet, move to next element
    
    return multi_sheet_refs


def create_multi_sheet_figure(multi_ref: Dict[str, Any], start_graphic_num: int = 0) -> Dict[str, Any]:
    """
    Создает элемент многолистовой иллюстрации для S1000D.
    """
    figure_num = multi_ref['figure_number']
    sheets = multi_ref['sheets']
    element = multi_ref['element']
    
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
        graphic_ident = f"GS5-A-120-10-00-00A-041A-A_001_RU-RU-GRAPHIC{graphic_num}"
        
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


def process_multi_sheet_illustrations(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Обрабатывает элементы и заменяет ссылки на многолистовые иллюстрации
    на соответствующие figure элементы.
    """
    # Находим все ссылки на многолистовые иллюстрации
    multi_sheet_refs = find_multi_sheet_references(elements)
    
    if not multi_sheet_refs:
        return elements
    
    # Группируем по номеру рисунка
    multi_sheet_by_figure = {}
    for ref in multi_sheet_refs:
        fig_num = ref['figure_number']
        if fig_num not in multi_sheet_by_figure:
            multi_sheet_by_figure[fig_num] = []
        multi_sheet_by_figure[fig_num].append(ref)
    
    # Определяем начальные номера для графических файлов
    # Находим все обычные иллюстрации для правильной нумерации
    regular_illustrations = [e for e in elements if e.get('type') == 'illustration' and not e.get('is_multi_sheet')]
    next_graphic_num = len(regular_illustrations)
    
    processed_elements = []
    processed_multi_sheet = set()
    
    for element in elements:
        # Проверяем, не является ли этот элемент ссылкой на многолистовую иллюстрацию
        is_multi_sheet_ref = False
        
        # ИСПРАВЛЕНИЕ: добавляем 'illustration_reference' в список типов
        if element.get('type') in ['paragraph', 'unnumbered_list', 'illustration_reference']:
            content = element.get('content', '')
            
            for fig_num, refs in multi_sheet_by_figure.items():
                if fig_num in processed_multi_sheet:
                    continue
                    
                # Проверяем, содержит ли элемент ссылку на этот рисунок
                if re.search(r'[Рр]исунок\s*' + str(fig_num), content, re.IGNORECASE):
                    # Это ссылка на многолистовую иллюстрацию
                    # Создаем figure элемент
                    multi_sheet_figure = create_multi_sheet_figure(refs[0], next_graphic_num)
                    processed_elements.append(multi_sheet_figure)
                    
                    # Обновляем счетчик графических файлов
                    next_graphic_num += len(refs[0]['sheets'])
                    
                    processed_multi_sheet.add(fig_num)
                    is_multi_sheet_ref = True
                    break
        
        if not is_multi_sheet_ref:
            # Проверяем, не является ли это обычной иллюстрацией, которая уже была обработана
            if element.get('type') == 'illustration':
                # Это может быть фигура, которую нужно пропустить, если она соответствует многолистовой
                content = element.get('content', '')
                fig_match = re.search(r'[Рр]исунок\s*(\d+)', content)
                if fig_match:
                    fig_num = int(fig_match.group(1))
                    if fig_num in processed_multi_sheet:
                        # Пропускаем эту иллюстрацию, так как она уже обработана как многолистовая
                        continue
            
            processed_elements.append(element)
    
    return processed_elements


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
