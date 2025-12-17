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


def analyze_document_elements(doc: Document, illustrations: Dict[str, str] = None, illustration_positions: Dict[str, Dict] = None) -> List[Dict[str, Any]]:
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

    # Track numbering state for numbered paragraph headers
    # This tracks the actual numbering sequence as it appears in the document
    numbering_counters = {}  # numId -> {ilvl -> counter}
    global_numbering_counter = 1  # Simple sequential counter for basic cases

    # Track cumulative text for position calculation
    line_number = 1
    char_position = 0

    # Process both paragraphs and tables in document order
    # Get all document elements (paragraphs and tables) in order
    doc_elements = []
    para_idx = 0
    table_idx = 0

    for element in doc.element.body:
        if element.tag.endswith('p'):  # Paragraph
            if para_idx < len(doc.paragraphs):
                doc_elements.append(('paragraph', para_idx))
                para_idx += 1
        elif element.tag.endswith('tbl'):  # Table
            if table_idx < len(doc.tables):
                doc_elements.append(('table', table_idx))
                table_idx += 1

    # Extract enhanced table data with titles
    from parsers.table_parser import extract_enhanced_tables_with_titles
    enhanced_tables = extract_enhanced_tables_with_titles(doc)

    # Process elements in document order
    current_table_idx = 0
    illustration_counter = 0  # Track illustration numbering for infoEntityIdent
    for i, (element_type, element_idx) in enumerate(doc_elements):
        if element_type == 'table':
            # Handle table element with enhanced data
            table_data = enhanced_tables[current_table_idx] if current_table_idx < len(enhanced_tables) else None
            current_table_idx += 1

            # Update position tracking for table
            table_start_line = line_number
            table_start_char = char_position

            # Approximate table size (simplified - assume 1 line per row)
            table_rows = len(table_data['rows']) if table_data else 1
            line_number += table_rows
            char_position = 0  # Reset to start of line

            table_end_line = line_number
            table_end_char = char_position

            # Create enhanced table XML
            if table_data:
                from parsers.table_parser import convert_enhanced_table_to_s1000d_format
                table_xml = convert_enhanced_table_to_s1000d_format(table_data)
            else:
                table_xml = '<table><tgroup cols="2"><tbody><row><entry>Ячейка 1</entry><entry>Ячейка 2</entry></row></tbody></tgroup></table>'

            # Create table element
            element_info = {
                'type': 'table',
                'start_line': table_start_line,
                'start_char': table_start_char,
                'end_line': table_end_line,
                'end_char': table_end_char,
                'start_para': para_idx,  # Use current para_idx as approximation
                'end_para': para_idx,
                'content': table_data.get('title', f'Таблица {element_idx + 1}') if table_data else f'Таблица {element_idx + 1}',
                'xml_example': table_xml,
                'details': f'Таблица {element_idx + 1}'
            }
            elements.append(element_info)
            continue
        else:
            # Handle paragraph element
            paragraph = doc.paragraphs[element_idx]
            para_idx = element_idx
            text = paragraph.text.strip()
            style_name = paragraph.style.name

            # Check for numbering properties
            numPr = None
            if hasattr(paragraph.paragraph_format, 'numPr') and paragraph.paragraph_format.numPr is not None:
                numPr = paragraph.paragraph_format.numPr
            else:
                # Fallback: check raw OOXML for numPr when python-docx fails to detect it
                # This happens with some DOCX files where numPr is present but not detected by python-docx
                try:
                    pPr_elem = paragraph._element.find('.//w:pPr', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
                    if pPr_elem is not None:
                        numPr_elem = pPr_elem.find('.//w:numPr', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
                        if numPr_elem is not None:
                            # Create a simple object to mimic numPr
                            class MockNumPr:
                                def __init__(self, numId_val, ilvl_val):
                                    self.numId_val = numId_val
                                    self.ilvl_val = ilvl_val

                                @property
                                def numId(self):
                                    class MockNumId:
                                        def __init__(self, val):
                                            self.val = val
                                    return MockNumId(self.numId_val)

                                @property
                                def ilvl(self):
                                    class MockIlvl:
                                        def __init__(self, val):
                                            self.val = val
                                    return MockIlvl(self.ilvl_val)

                            # Extract values from raw XML
                            ilvl_elem = numPr_elem.find('.//w:ilvl', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
                            numId_elem = numPr_elem.find('.//w:numId', {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})

                            ilvl_val = int(ilvl_elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '0')) if ilvl_elem is not None else 0
                            numId_val = int(numId_elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '0')) if numId_elem is not None else 0

                            if numId_val > 0:  # Only consider it valid if numId is present
                                numPr = MockNumPr(numId_val, ilvl_val)
                except Exception as e:
                    # If anything fails, just continue without numPr
                    # print(f"FALLBACK FAILED for para {para_idx}: {e}")
                    pass

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

        # Detect numbered paragraph headers first
        # (paragraphs with numbering properties that appear as numbered headings)
        is_numbered_header = False
        level = 1

        if numPr is not None:
            # Check if this has numbering and looks like a header
            # Either has Heading style, or has specific header-like content, or just has numbering
            if (style_name.startswith('Heading') or
                style_name in ['1', '2', '3', '4', '5', '6', '7', '8', '9'] or  # Numeric style names like "2"
                # More inclusive check: short text without sentence-ending punctuation
                (len(text.strip()) < 200 and not text.endswith(('.', '!', '?')) and
                 not any(word in text.lower() for word in ['представляет', 'обеспечивает', 'осуществляет', 'является', 'который', 'которая', 'которое', 'которые'])) or
                # Or if it starts with typical header words
                any(text.strip().startswith(word) for word in ['ОБЩИЕ', 'СОСТАВ', 'ОПИСАНИЕ', 'Пульт', 'Блок', 'Рама', 'Таблица', 'Рисунок'])):
                is_numbered_header = True

                # Extract level from style name if possible
                if style_name.startswith('Heading'):
                    level_match = re.search(r'Heading\s*(\d+)', style_name, re.IGNORECASE)
                    level = int(level_match.group(1)) if level_match else 1
                elif style_name.isdigit():
                    level = int(style_name)

        if is_numbered_header:
            # Extract the header part and any remaining content
            header_text = ""
            remaining_content = ""

            # Try to split on newlines first
            if '\n' in text:
                lines = text.split('\n', 1)
                header_text = lines[0].strip()
                remaining_content = lines[1].strip() if len(lines) > 1 else ""
            else:
                # No newlines, try to identify header patterns
                # Look for common header patterns followed by content
                header_patterns = [
                    (r'^([ОБЩИЕ СВЕДЕНИЯ]+)\s+(.+)', 'ОБЩИЕ СВЕДЕНИЯ'),
                    (r'^([СОСТАВ РСУО]+)\s+(.+)', 'СОСТАВ РСУО'),
                    (r'^([АВТОМАТИЧЕСКИЙ РЕЖИМ РАБОТЫ РСУО]+)\s+(.+)', 'АВТОМАТИЧЕСКИЙ РЕЖИМ РАБОТЫ РСУО'),
                    (r'^([АВТОНОМНЫЙ РЕЖИМ РАБОТЫ РСУО]+)\s+(.+)', 'АВТОНОМНЫЙ РЕЖИМ РАБОТЫ РСУО'),
                    (r'^([АВАРИЙНЫЙ РЕЖИМ РАБОТЫ РСУО]+)\s+(.+)', 'АВАРИЙНЫЙ РЕЖИМ РАБОТЫ РСУО'),
                    (r'^([УЧЕБНО-ТРЕНИРОВОЧНЫЙ РЕЖИМ РАБОТЫ РСУО]+)\s+(.+)', 'УЧЕБНО-ТРЕНИРОВОЧНЫЙ РЕЖИМ РАБОТЫ РСУО'),
                    (r'^([РЕЖИМ УПРАВЛЕНИЯ СТВОРКАМИ ГРУЗОВЫХ ОТСЕКОВ]+)\s+(.+)', 'РЕЖИМ УПРАВЛЕНИЯ СТВОРКАМИ ГРУЗОВЫХ ОТСЕКОВ'),
                ]

                for pattern, expected_header in header_patterns:
                    match = re.match(pattern, text, re.IGNORECASE)
                    if match and match.group(1).strip().upper() == expected_header.upper():
                        header_text = match.group(1).strip()
                        remaining_content = match.group(2).strip()
                        break

                # If no pattern matched, assume the whole text is header (fallback)
                if not header_text:
                    header_text = text.strip()

            # Get numbering values
            ilvl_val = 0
            numId_val = 0
            if hasattr(numPr, 'ilvl') and hasattr(numPr, 'numId'):
                ilvl_val = numPr.ilvl.val if hasattr(numPr.ilvl, 'val') else numPr.ilvl
                numId_val = numPr.numId.val if hasattr(numPr.numId, 'val') else numPr.numId

            # Track numbering state and get the correct number
            if numId_val not in numbering_counters:
                numbering_counters[numId_val] = {}
            if ilvl_val not in numbering_counters[numId_val]:
                numbering_counters[numId_val][ilvl_val] = 0

            # Increment counter for this level
            numbering_counters[numId_val][ilvl_val] += 1
            current_number = numbering_counters[numId_val][ilvl_val]

            # Create numbering prefix based on level
            numbering_prefix = f"{current_number}."

            # Combine numbering with header text
            numbered_title = f"{numbering_prefix} {header_text}".strip()

            # Add the numbered paragraph header
            element_info = {
                'type': 'numbered_paragraph_header',
                'start_line': para_start_line,
                'start_char': para_start_char,
                'end_line': para_end_line if not remaining_content else para_start_line,  # Adjust end line if content follows
                'end_char': para_end_char if not remaining_content else para_start_char + len(header_text),
                'start_para': para_idx,
                'end_para': para_idx,
                'content': numbered_title,  # Include numbering in content
                'xml_example': f'<levelledPara><title>{numbered_title}</title></levelledPara>',
                'details': f'Нумерованный заголовок параграфа (уровень {level})'
            }
            elements.append(element_info)

            # If there's remaining content, add it as a separate paragraph
            if remaining_content:
                para_content_start_line = para_start_line  # Same line
                para_content_start_char = para_start_char + len(header_text) + 1  # After header + space

                element_info_content = {
                    'type': 'paragraph',
                    'start_line': para_content_start_line,
                    'start_char': para_content_start_char,
                    'end_line': para_end_line,
                    'end_char': para_end_char,
                    'start_para': para_idx,
                    'end_para': para_idx,
                    'content': remaining_content,
                    'xml_example': f'<para>{remaining_content}</para>',
                    'details': 'Параграф'
                }
                elements.append(element_info_content)

            continue

        # Detect regular headers/headings - only treat as header if it looks like a proper section header
        if style_name.startswith('Heading'):
            level_match = re.search(r'Heading\s*(\d+)', style_name, re.IGNORECASE)
            level = int(level_match.group(1)) if level_match else 1

            # Check if this looks like a real section header (short, title-like text)
            # If it's long or contains sentence structure, treat as regular paragraph
            is_real_header = (
                len(text) < 100 and  # Short text
                not text.endswith(':') and  # Not ending with colon (descriptive)
                not any(word in text.lower() for word in ['представляет', 'обеспечивает', 'осуществляет', 'является', 'таблица', 'рисунок', 'указан'])  # Not descriptive sentences or references
            )

            if not is_real_header:
                # Treat as regular paragraph instead
                pass  # Fall through to paragraph processing
            elif '\n' in text:
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

        # Detect main section headers (like 1., 2., etc.) - treat as numbered paragraph headers
        if _is_main_section_header(text):
            element_info = {
                'type': 'numbered_paragraph_header',
                'start_line': para_start_line,
                'start_char': para_start_char,
                'end_line': para_end_line,
                'end_char': para_end_char,
                'start_para': para_idx,
                'end_para': para_idx,
                'content': text,
                'xml_example': f'<levelledPara><title>{text}</title></levelledPara>',
                'details': 'Нумерованный заголовок параграфа'
            }
            elements.append(element_info)
            continue

        # Detect lists
        list_type = _get_list_type(paragraph, para_idx)
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
            # Use the correct GRAPHIC identifier based on counter
            graphic_ident = f"GS5-A-120-10-00-00A-041A-A_001_RU-RU-GRAPHIC{illustration_counter}"
            element_info = {
                'type': 'illustration',
                'start_line': para_start_line,
                'start_char': para_start_char,
                'end_line': para_end_line,
                'end_char': para_end_char,
                'start_para': para_idx,
                'end_para': para_idx,
                'content': 'Иллюстрация',
                'xml_example': f'<figure><title>Название иллюстрации</title><graphic infoEntityIdent="{graphic_ident}"/></figure>',
                'details': 'Встраиваемая иллюстрация'
            }
            elements.append(element_info)
            illustration_counter += 1
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
                'xml_example': '<warning><warningAndCautionPara>Предупреждающий текст</warningAndCautionPara></warning>',
                'details': 'Предупреждение/Предупреждение'
            }
            elements.append(element_info)
            continue

        # Detect references
        references = _find_references(text)
        for ref_data in references:
            if len(ref_data) == 4:  # illustration_reference with icn_ref
                ref_type, ref_number, context, icn_ref = ref_data
            else:  # other references
                ref_type, ref_number, context = ref_data
                icn_ref = None

            xml_example = {
                'table_reference': '<para>Ссылка на таблицу: <tableRef refType="tableref" refIdent="TAB0001"/></para>',
                'illustration_reference': f'<para>Ссылка на рисунок: <internalRef internalRefId="ICN{int(ref_number):02d}" internalRefTargetType="irtt01"/></para>',
                'data_module_reference': '<para>Ссылка на модуль данных: <dmRef refType="refdm" refIdent="DMC-S5-A-120-10-00-00A-011A-A"/></para>'
            }.get(ref_type, '<para>Ссылка</para>')

            # Add file info for illustration references
            if ref_type == 'illustration_reference':
                # Use sequential numbering for references
                if not hasattr(analyze_document_elements, 'global_illustration_ref_counter'):
                    analyze_document_elements.global_illustration_ref_counter = 0
                ref_number = analyze_document_elements.global_illustration_ref_counter + 1
                analyze_document_elements.global_illustration_ref_counter += 1

                # Use sequential numbering for graphic files (will be updated in post-processing)
                graphic_num = int(ref_number) - 1  # Will be corrected in post-processing
                graphic_file = f"GS5-A-120-10-00-00A-041A-A_001_RU-RU-GRAPHIC{graphic_num}.jpg"
                details = f'Ссылка на {ref_type} {ref_number}, file: {graphic_file}'
            else:
                details = f'Ссылка на {ref_type} {ref_number}'

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
                'details': details
            }
            elements.append(element_info)

        # Default: paragraph
        # If text has multiple lines, treat first line as title, rest as content
        if '\n' in text:
            lines = text.split('\n', 1)
            title = lines[0].strip()
            body = lines[1].strip()
            content = f'{title} {body}'
            xml_example = f'<para>{title} {body}</para>'
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

    # Post-process elements to clean up table references in paragraphs that precede tables
    # and combine illustration references with figure name paragraphs
    processed_elements = []
    i = 0
    while i < len(elements):
        # Check for illustration_reference followed by figure name paragraph
        if (i < len(elements) - 1 and
            elements[i].get('type') == 'illustration_reference' and
            elements[i + 1].get('type') == 'paragraph'):
            figure_content = elements[i + 1].get('content', '').strip()
            figure_name_pattern = r'^[Рр]исунок\s*\d+\s*[–-]\s*.+'
            if re.match(figure_name_pattern, figure_content):
                # Extract ICN number from illustration_reference details
                details = elements[i].get('details', '')
                icn_match = re.search(r'illustration_reference (\d+)', details)
                icn_num = icn_match.group(1) if icn_match else '01'
                icn_ref = f"ICN{int(icn_num):02d}"

                # Use sequential graphic numbering starting from 0
                # This matches what extract_illustrations would save
                if not hasattr(analyze_document_elements, 'graphic_counter'):
                    analyze_document_elements.graphic_counter = 0
                graphic_num = analyze_document_elements.graphic_counter
                analyze_document_elements.graphic_counter += 1

                graphic_file = f"GS5-A-120-10-00-00A-041A-A_001_RU-RU-GRAPHIC{graphic_num}.jpg"

                # Create combined illustration element
                # Use position information from illustration_positions if available
                ref_name = f"GS5-A-120-10-00-00A-041A-A_001_RU-RU-GRAPHIC{graphic_num}"
                pos_info = illustration_positions.get(ref_name, {}) if illustration_positions else {}
                combined_elem = {
                    'type': 'illustration',
                    'start_line': pos_info.get('start_line', elements[i].get('start_line', 0)),
                    'start_char': pos_info.get('start_char', elements[i].get('start_char', 0)),
                    'end_line': pos_info.get('end_line', elements[i + 1].get('end_line', elements[i].get('end_line', 0))),
                    'end_char': pos_info.get('end_char', elements[i + 1].get('end_char', elements[i].get('end_char', 0))),
                    'start_para': pos_info.get('start_para', elements[i].get('start_para', 0)),
                    'end_para': pos_info.get('end_para', elements[i + 1].get('end_para', elements[i].get('end_para', 0))),
                    'content': figure_content,
                    'xml_example': f'<figure id="{icn_ref}"><title>{figure_content}</title><graphic infoEntityIdent="GS5-A-120-10-00-00A-041A-A_001_RU-RU-GRAPHIC{graphic_num}" reproductionScale="32" reproductionWidth="170mm" reproductionHeight="120mm" id="g{int(icn_num)}"/></figure>',
                    'details': f'Иллюстрация {icn_num}, file: {graphic_file}',
                    'context_text': pos_info.get('context_text', '')
                }
                processed_elements.append(combined_elem)
                i += 2  # Skip both elements
                continue

        # Check for table references in paragraphs
        elem = elements[i]
        elem_type = elem.get('type', 'paragraph')
        content = elem.get('content', '')

        if elem_type == 'paragraph' and i < len(elements) - 1:
            next_elem = elements[i + 1]
            if next_elem.get('type') == 'table':
                table_title = next_elem.get('content', '')
                if table_title:
                    # Remove table references from paragraph content
                    patterns = [
                        r'\s*\([Тт]аблица\s*\d+\)\s*',
                        r'\s*[Тт]аблица\s*\d+\s*',
                        r'\s*[Тт]аб\.\s*\d+\s*',
                        r'\s*[Тт]абл\.\s*\d+\s*'
                    ]
                    for pattern in patterns:
                        content = re.sub(pattern, '', content, flags=re.IGNORECASE)

                    # Clean up extra whitespace and trailing punctuation
                    content = content.strip()
                    if content.endswith('.,'):
                        content = content[:-2]
                    elif content.endswith(','):
                        content = content[:-1]
                    elif content.endswith('.'):
                        pass  # Keep the period
                    else:
                        pass

                    # Update the element content and XML example
                    elem = elem.copy()
                    elem['content'] = content
                    elem['xml_example'] = f'<para>{content}</para>'

        processed_elements.append(elem)
        i += 1

    return processed_elements


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


def _get_list_type(paragraph, para_idx: int = None) -> str:
    """Get list type for paragraph based on OOXML formatting and enhanced heuristics."""
    text = paragraph.text.strip()

    # Skip section headers
    if _is_main_section_header(text):
        return ''

    # First try OOXML formatting (preferred method)
    if hasattr(paragraph.paragraph_format, 'numPr') and paragraph.paragraph_format.numPr is not None:
        # Get numId to determine list type
        num_id = paragraph.paragraph_format.numPr.numId
        if num_id is not None:
            # Access document numbering to determine if numbered or bulleted
            doc = paragraph.part.document
            numbering_part = doc.numbering_part
            if numbering_part is not None:
                try:
                    num = numbering_part.nums[num_id.val]
                    abstract_num = numbering_part.abstract_nums[num.abstract_num_id.val]
                    # Check lvl0 lvlText to determine list type - if contains % it's numbered
                    lvl0 = abstract_num.lvl0
                    if lvl0 is not None and hasattr(lvl0, 'lvlText') and lvl0.lvlText is not None:
                        lvl_text = lvl0.lvlText.val
                        if '%' in lvl_text:
                            return 'numbered_list'
                        else:
                            return 'unnumbered_list'
                    else:
                        # Fallback to numFmt if lvlText not available
                        if hasattr(abstract_num, 'num_style_link') and abstract_num.num_style_link is not None:
                            # If linked to a style, check if it's a numbered style
                            style_name = abstract_num.num_style_link.val.lower()
                            if 'number' in style_name or 'decimal' in style_name:
                                return 'numbered_list'
                            else:
                                return 'unnumbered_list'
                        else:
                            # Check lvl0 numFmt directly
                            lvl0 = abstract_num.lvl0
                            if lvl0 is not None and hasattr(lvl0, 'numFmt') and lvl0.numFmt is not None:
                                num_fmt = lvl0.numFmt.val.lower()
                                if num_fmt in ['decimal', 'lowerroman', 'upperroman', 'lowerletter', 'upperletter']:
                                    return 'numbered_list'
                                else:
                                    return 'unnumbered_list'
                            else:
                                return 'unnumbered_list'
                except (KeyError, AttributeError):
                    return 'unnumbered_list'
            else:
                return 'unnumbered_list'
        else:
            return 'unnumbered_list'

    # Fallback to enhanced heuristics if no OOXML formatting found
    doc = paragraph.part.document
    
    # If para_idx not provided, find it
    if para_idx is None:
        for idx, p in enumerate(doc.paragraphs):
            if p == paragraph:
                para_idx = idx
                break
    
    if para_idx is None:
        return ''
    
    # Check for list markers in text
    unnumbered_markers = ['•', '◦', '▪', '▫', '⁃', '·', '-', '–', '—', '*', '†', '‡', '§']
    if any(text.startswith(marker) for marker in unnumbered_markers):
        return 'unnumbered_list'
    
    # Check if text ends with ';' (typical for list items)
    if text.endswith(';'):
        # Verify it's after an intro paragraph ending with ':'
        if _is_after_colon_intro(doc, para_idx):
            return 'unnumbered_list'
    
    # Check colon-intro pattern
    list_type = _detect_colon_intro_list(doc, para_idx)
    if list_type:
        return list_type

    return ''


def _is_after_colon_intro(doc, para_idx: int) -> bool:
    """Check if paragraph is after an introductory paragraph ending with ':'."""
    paragraphs = doc.paragraphs
    
    # Search backward for introductory paragraph ending with ":"
    for idx in range(para_idx - 1, -1, -1):
        para = paragraphs[idx]
        text = para.text.strip()
        if not text:
            # Empty line - check if it breaks the list
            continue
        if text.endswith(':'):
            return True
        # If we hit a paragraph that doesn't end with ':', ';' or is empty, stop
        if not text.endswith(';') and not text.endswith(':'):
            break
    
    return False


def _detect_colon_intro_list(doc, para_idx: int) -> str:
    """
    Detect if paragraph is part of a list that starts after a colon-ending intro.
    """
    paragraphs = doc.paragraphs
    text = paragraphs[para_idx].text.strip()
    
    # Search backward for introductory paragraph ending with ":"
    intro_idx = None
    for idx in range(para_idx - 1, -1, -1):
        para = paragraphs[idx]
        para_text = para.text.strip()
        if not para_text:
            # Empty line means we've passed the list boundary
            break
        if para_text.endswith(':'):
            intro_idx = idx
            break
    
    if intro_idx is None:
        return ''
    
    # Check if current paragraph is within the list items after intro
    # List ends at empty line or at another line ending with ':'
    current_idx = intro_idx + 1
    list_items_indices = []
    
    while current_idx < len(paragraphs):
        para = paragraphs[current_idx]
        para_text = para.text.strip()
        
        # Empty line ends the list
        if not para_text:
            break
        
        # Another introductory line ends this list
        if para_text.endswith(':'):
            break
        
        list_items_indices.append(current_idx)
        current_idx += 1
    
    # If current paragraph is in the list items, return unnumbered_list
    if para_idx in list_items_indices and len(list_items_indices) >= 1:
        return 'unnumbered_list'
    
    return ''


def _clean_list_item_text(paragraph, list_type: str) -> str:
    """Clean list item text by removing markers and formatting."""
    text = paragraph.text.strip()

    if list_type == 'unnumbered_list':
        # Remove common unnumbered list markers
        unnumbered_markers = [
            '•', '◦', '▪', '▫', '⁃', '·', '·', '•', '-', '–', '—', '*', '†', '‡', '§'
        ]
        for marker in unnumbered_markers:
            if text.startswith(marker):
                text = text[len(marker):].strip()
                break
    elif list_type == 'numbered_list':
        # Remove numbered list markers using regex
        import re
        numbered_patterns = [
            r'^\d+\.\s*',  # 1., 2., 10.
            r'^\d+\)\s*',  # 1), 2), 10)
            r'^\(\d+\)\s*',  # (1), (2), (10)
            r'^\d+\s*[.)]\s*',  # 1 , 1), 2 , etc.
            r'^[a-zA-Z]\.\s*',  # a., b., A., B.
            r'^[a-zA-Z]\)\s*',  # a), b), A), B)
            r'^\([a-zA-Z]\)\s*',  # (a), (b), (A), (B)
            r'^[IVXLCDM]+\.\s*',  # I., II., III. (Roman numerals)
            r'^[ivxlcdm]+\.\s*',  # i., ii., iii. (Roman numerals)
            r'^[IVXLCDM]+\)\s*',  # I), II), III)
            r'^[ivxlcdm]+\)\s*',  # i), ii), iii)
        ]
        for pattern in numbered_patterns:
            text = re.sub(pattern, '', text, count=1)
            if text != paragraph.text.strip():  # If something was removed
                break

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

    # Illustration/Figure references - include regular figure mentions
    figure_patterns = [
        r'^[Рр]исунок\s*(\d+)\s*[–-]\s*.+',
        r'\b[Рр]ис\.\s*(\d+)',
        r'\b[Фф]igure\s*(\d+)',
    ]
    for pattern in figure_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            # ICN will be assigned sequentially later in processing
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
        'numbered_paragraph_header': 'Нумерованный заголовок параграфа',
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
