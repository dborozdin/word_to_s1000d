"""
Element analyzer for Word documents.
Analyzes document structure and generates logs of all detected elements.
"""

import os
import re
from typing import Dict, List, Tuple, Any
from docx import Document
from docx.shared import Inches
import datetime


def analyze_document_elements(doc: Document) -> List[Dict[str, Any]]:
    """
    Analyze document and extract all elements with their start/end positions.

    Args:
        doc: Word document object

    Returns:
        List of element dictionaries with type, start_para, end_para, content, xml_example
    """
    elements = []

    # Track list state
    current_list = None
    list_start_para = 0

    # Track cumulative text for position calculation
    line_number = 1
    char_position = 0

    # Process paragraphs
    for para_idx, paragraph in enumerate(doc.paragraphs):
        text = paragraph.text.strip()
        style_name = paragraph.style.name

        # Update position tracking
        para_start_line = line_number
        para_start_char = char_position

        # Add paragraph text to cumulative text (including original formatting for position tracking)
        original_text = paragraph.text

        # Count newlines and characters
        newline_count = original_text.count('\n')
        line_number += newline_count
        if newline_count > 0:
            char_position = len(original_text.split('\n')[-1])
        else:
            char_position += len(original_text)

        para_end_line = line_number
        para_end_char = char_position

        if not text:
            continue

        # Detect table paragraphs (tables appear as special paragraphs)
        if _is_table_start(paragraph):
            element_info = {
                'type': 'table',
                'start_line': para_start_line,
                'start_char': para_start_char,
                'end_line': para_end_line,
                'end_char': para_end_char,
                'start_para': para_idx,
                'end_para': para_idx,  # Tables might span multiple paras, but for simplicity
                'content': 'Таблица',
                'xml_example': '<table><tgroup cols="2"><tbody><row><entry>Ячейка 1</entry><entry>Ячейка 2</entry></row></tbody></tgroup></table>',
                'details': 'Таблица'
            }
            elements.append(element_info)
            continue

        # Detect headers/headings
        if style_name.startswith('Heading'):
            level_match = re.search(r'Heading\s*(\d+)', style_name, re.IGNORECASE)
            level = int(level_match.group(1)) if level_match else 1

            # If text has multiple lines, treat first line as title, rest as separate paragraph
            if '\n' in text:
                lines = text.split('\n', 1)
                title = lines[0].strip()
                body = lines[1].strip()
                # Add header
                element_info = {
                    'type': 'header',
                    'start_line': para_start_line,
                    'start_char': para_start_char,
                    'end_line': para_start_line,  # Header ends at first line
                    'end_char': para_start_char + len(lines[0]),
                    'start_para': para_idx,
                    'end_para': para_idx,
                    'content': title,
                    'xml_example': f'<levelledPara><title>{title}</title></levelledPara>',
                    'details': f'Уровень {level}'
                }
                elements.append(element_info)
                # Add paragraph for the rest
                if body:
                    para_start_line_body = para_start_line + 1
                    para_start_char_body = 0  # Assume new line
                    element_info_para = {
                        'type': 'paragraph',
                        'start_line': para_start_line_body,
                        'start_char': para_start_char_body,
                        'end_line': para_end_line,
                        'end_char': para_end_char,
                        'start_para': para_idx,
                        'end_para': para_idx,
                        'content': body,
                        'xml_example': f'<para>{body}</para>',
                        'details': 'Параграф'
                    }
                    elements.append(element_info_para)
                continue
            else:
                element_info = {
                    'type': 'header',
                    'start_line': para_start_line,
                    'start_char': para_start_char,
                    'end_line': para_end_line,
                    'end_char': para_end_char,
                    'start_para': para_idx,
                    'end_para': para_idx,
                    'content': text,
                    'xml_example': f'<levelledPara><title>{text}</title></levelledPara>',
                    'details': f'Уровень {level}'
                }
                elements.append(element_info)
                continue

        # Detect main section headers (like 1., 2., etc.)
        if _is_main_section_header(text):
            element_info = {
                'type': 'header',
                'start_line': para_start_line,
                'start_char': para_start_char,
                'end_line': para_end_line,
                'end_char': para_end_char,
                'start_para': para_idx,
                'end_para': para_idx,
                'content': text,
                'xml_example': f'<levelledPara><title>{text}</title></levelledPara>',
                'details': 'Уровень 1'
            }
            elements.append(element_info)
            continue

        # Detect lists
        list_type = _get_list_type(paragraph)
        if list_type:
            if current_list != list_type:
                # End previous list if any
                if current_list:
                    # Update end_para for previous list items
                    _update_list_end_para(elements, para_idx - 1)

                # Start new list
                current_list = list_type
                list_start_para = para_idx

            # Add list item
            clean_text = _clean_list_item_text(paragraph, list_type)
            xml_prefix = 'pf02' if list_type == 'unnumbered_list' else 'nfp01'
            xml_example = f'<randomList listItemPrefix="{xml_prefix}"><listItem><para>{clean_text}</para></listItem></randomList>'

            element_info = {
                'type': list_type,
                'start_line': para_start_line,
                'start_char': para_start_char,
                'end_line': para_end_line,
                'end_char': para_end_char,
                'start_para': para_idx,
                'end_para': para_idx,  # Will be updated when list ends
                'content': clean_text,
                'xml_example': xml_example,
                'details': f'Элемент списка ({list_type})'
            }
            elements.append(element_info)
            continue
        else:
            # End current list if it was ongoing
            if current_list:
                _update_list_end_para(elements, para_idx - 1)
                current_list = None

        # Detect illustrations (embedded images in paragraphs)
        if _has_embedded_image(paragraph):
            element_info = {
                'type': 'illustration',
                'start_line': para_start_line,
                'start_char': para_start_char,
                'end_line': para_end_line,
                'end_char': para_end_char,
                'start_para': para_idx,
                'end_para': para_idx,
                'content': 'Иллюстрация',
                'xml_example': '<figure><title>Название иллюстрации</title><graphic infoEntityIdent="GS5-A-120-10-00-00A-041A-A_001_RU-RU-GRAPHIC0"/></figure>',
                'details': 'Встраиваемая иллюстрация'
            }
            elements.append(element_info)
            continue

        # Detect warnings/cautions
        if _is_warning(text):
            element_info = {
                'type': 'warning',
                'start_line': para_start_line,
                'start_char': para_start_char,
                'end_line': para_end_line,
                'end_char': para_end_char,
                'start_para': para_idx,
                'end_para': para_idx,
                'content': text,
                'xml_example': '<warning><para>Предупреждающий текст</para></warning>',
                'details': 'Предупреждение/Предупреждение'
            }
            elements.append(element_info)
            continue

        # Detect references
        references = _find_references(text)
        for ref_type, ref_number, context in references:
            xml_example = {
                'table_reference': '<para>Ссылка на таблицу: <tableRef refType="tableref" refIdent="TAB0001"/></para>',
                'illustration_reference': '<para>Ссылка на рисунок: <icn icnType="irtt" refIdent="ICN0001"/></para>',
                'data_module_reference': '<para>Ссылка на модуль данных: <dmRef refType="refdm" refIdent="DMC-S5-A-120-10-00-00A-011A-A"/></para>'
            }.get(ref_type, '<para>Ссылка</para>')

            element_info = {
                'type': ref_type,
                'start_line': para_start_line,
                'start_char': para_start_char,
                'end_line': para_end_line,
                'end_char': para_end_char,
                'start_para': para_idx,
                'end_para': para_idx,
                'content': f'Ссылка на {context} {ref_number}',
                'xml_example': xml_example,
                'details': f'Ссылка на {ref_type} {ref_number}'
            }
            elements.append(element_info)

        # Default: paragraph
        # If text has multiple lines, treat first line as title, rest as content
        if '\n' in text:
            lines = text.split('\n', 1)
            title = lines[0].strip()
            body = lines[1].strip()
            content = f'<title>{title}</title>{body}'
            xml_example = f'<para><title>{title}</title>{body}</para>'
        else:
            content = text
            xml_example = f'<para>{text}</para>'

        element_info = {
            'type': 'paragraph',
            'start_line': para_start_line,
            'start_char': para_start_char,
            'end_line': para_end_line,
            'end_char': para_end_char,
            'start_para': para_idx,
            'end_para': para_idx,
            'content': content,
            'xml_example': xml_example,
            'details': 'Параграф'
        }
        elements.append(element_info)

    # Close any remaining list
    if current_list:
        _update_list_end_para(elements, len(doc.paragraphs) - 1)

    return elements


def _is_table_start(paragraph) -> bool:
    """Check if paragraph starts a table (simplified check)."""
    # This is a basic check; tables in docx don't directly correspond to paragraphs this way
    # In python-docx, tables are separate, but for logging purposes, we can detect them elsewhere
    # For now, return False; tables will be handled separately if needed
    return False


def _is_main_section_header(text: str) -> bool:
    """Check if text is a main section header (1., 2., 3., etc.)."""
    pattern = r'^\s*\d+\.?\s+'
    return bool(re.match(pattern, text))


def _get_list_type(paragraph) -> str:
    """Get list type for paragraph."""
    text = paragraph.text.strip()

    # Skip section headers
    if _is_main_section_header(text):
        return ''

    # Check if paragraph is formatted as a list in Word
    if hasattr(paragraph.paragraph_format, 'numPr') and paragraph.paragraph_format.numPr is not None:
        return 'unnumbered_list'

    # Check for bullet markers at the start of the paragraph text (more robust)
    if (text.startswith('•') or text.startswith('◦') or text.startswith('-') or
        text.startswith('–') or text.startswith('—') or text.startswith('·')):
        return 'unnumbered_list'

    # Check for numbered markers
    if any(text.startswith(str(i) + '.') for i in range(1, 10)):
        return 'numbered_list'

    # Check for indentation (heuristic)
    if paragraph.paragraph_format.left_indent and paragraph.paragraph_format.left_indent > Inches(0):
        # Indented paragraphs are likely lists
        # Special case for long paragraphs ending with '.' (common in Russian documents)
        if len(text) >= 100 and text.strip().endswith('.'):
            return 'unnumbered_list'
        return 'unnumbered_list'

    # Special case for long paragraphs ending with '.' even if not indented
    if len(text) >= 100 and text.strip().endswith('.'):
        return 'unnumbered_list'

    # Heuristic for list items ending with semicolon (common in Russian documents)
    if text.strip().endswith(';') and len(text.strip()) < 200:
        return 'unnumbered_list'

    return ''


def _clean_list_item_text(paragraph, list_type: str) -> str:
    """Clean list item text by removing markers."""
    text = paragraph.text
    if list_type == 'unnumbered_list':
        text = re.sub(r'^[•◦\-\–—·]\s*', '', text)
    elif list_type == 'numbered_list':
        text = re.sub(r'^\d+\.\s*', '', text)
    return text.strip()


def _update_list_end_para(elements: List[Dict], end_para: int):
    """Update end_para for the last list items."""
    for element in reversed(elements):
        if element['type'] in ['numbered_list', 'unnumbered_list']:
            element['end_para'] = end_para
            if element.get('xml_example') and 'listItem' in element['xml_example']:
                # It's a single item, no need to update further
                break
        else:
            break


def _has_embedded_image(paragraph) -> bool:
    """Check if paragraph contains embedded image."""
    for run in paragraph.runs:
        if run.element.xpath('.//a:blip'):
            return True
    return False


def _is_warning(text: str) -> bool:
    """Check if text contains warning/caution content."""
    lower_text = text.lower()
    warning_keywords = ['внимание', 'осторожно', 'предупреждение', 'caution', 'warning', 'опасно']
    return any(keyword in lower_text for keyword in warning_keywords)


def _find_references(text: str) -> List[Tuple[str, str, str]]:
    """Find various references in text."""
    references = []

    # Table references
    table_patterns = [
        r'\b[Тт]аблица\s*(\d+)',
        r'\b[Тт]абл\.\s*(\d+)',
        r'\bTable\s*(\d+)',
    ]
    for pattern in table_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            references.append(('table_reference', match, 'таблицу'))

    # Illustration/Figure references
    figure_patterns = [
        r'\b[Рр]исунок\s*(\d+)',
        r'\b[Рр]ис\.\s*(\d+)',
        r'\b[Фф]igure\s*(\d+)',
        r'\b[Ии]ллюстрация\s*(\d+)',
    ]
    for pattern in figure_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            references.append(('illustration_reference', match, 'иллюстрацию'))

    # Data module references (more complex, might be DM codes)
    dm_patterns = [
        r'\bDMC-[A-Z]\d+-[A-Z]-(\d+)-.*?\b',
        r'\bМодуль\s*данных\s*(\d+)',
    ]
    for pattern in dm_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            for match in matches:
                references.append(('data_module_reference', match, 'модуль данных'))

    return references


def generate_elements_log(document_path: str, elements: List[Dict[str, Any]], output_path: str) -> str:
    """
    Generate elements log file for a document.

    Args:
        document_path: Path to source document
        elements: List of element dictionaries
        output_path: Directory to save log file

    Returns:
        Path to generated log file
    """
    filename = os.path.basename(document_path).replace('.docx', '').replace('.doc', '')
    log_path = os.path.join(output_path, f"elements_{filename}.log")

    element_type_names = {
        'header': 'Заголовок',
        'paragraph': 'Параграф',
        'numbered_list': 'Нумерованный список',
        'unnumbered_list': 'Ненумерованный список',
        'table': 'Таблица',
        'illustration': 'Иллюстрация',
        'table_reference': 'Ссылка на таблицу',
        'illustration_reference': 'Ссылка на иллюстрацию',
        'data_module_reference': 'Ссылка на модуль данных',
        'warning': 'Предупреждение'
    }

    with open(log_path, 'w', encoding='utf-8') as f:
        f.write("Анализ элементов документа\n")
        f.write(f"Сгенерировано: {datetime.datetime.now()}\n")
        f.write(f"Исходный файл: {document_path}\n")
        f.write("=" * 80 + "\n\n")

        for i, element in enumerate(elements, 1):
            element_type = element['type']
            type_name = element_type_names.get(element_type, element_type)

            f.write(f"Элемент {i}: {type_name}\n")

            # Position information
            if 'start_line' in element:
                f.write(f"  Позиция: строка {element['start_line']}, символ {element['start_char']}\n")
                if element.get('end_line') != element['start_line'] or element.get('end_char') != element['start_char']:
                    f.write(f"  Конец: строка {element.get('end_line', element['start_line'])}, символ {element.get('end_char', element['start_char'])}\n")

            # Content with more text shown
            content = element['content']
            if len(content) > 200:
                f.write(f"  Содержание: {content[:200]}...\n")
            else:
                f.write(f"  Содержание: {content}\n")

            if element.get('details'):
                f.write(f"  Детали: {element['details']}\n")

            f.write(f"  Пример XML: {element['xml_example']}\n")
            f.write("\n" + "-" * 80 + "\n\n")

    print(f"Лог элементов сохранен в: {log_path}")
    return log_path
