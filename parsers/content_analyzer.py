"""
Content analyzer for Word documents.
Analyzes document structure and assigns appropriate info_name values for S1000D modules.
"""

import re
from typing import Dict, List, Tuple, Optional
from docx import Document


def analyze_document_content(document: Document) -> List[Dict]:
    """
    Analyze document content and extract sections for S1000D modules.

    Args:
        document: Word document object

    Returns:
        List of section dictionaries with content analysis
    """
    sections = []
    current_section = None

    # Track paragraph indices for block references
    for para_idx, paragraph in enumerate(document.paragraphs):
        text = paragraph.text.strip()

        if not text:
            continue

        # Check for main section headers (Heading style or numeric)
        if paragraph.style.name.startswith('Heading') or _is_main_section_header(text):
            if current_section:
                # Close previous section
                current_section['end_para'] = para_idx - 1
                sections.append(current_section)

            current_section = _analyze_section_header(text, para_idx)
            if current_section:
                current_section['start_para'] = para_idx

        elif current_section:
            # Check if this is an equipment listing that should be a separate component section
            if _is_equipment_listing(text) and current_section.get('section_type') == 'description':
                # Create separate equipment component section
                equipment_info = _create_equipment_section(text, para_idx)
                if equipment_info:
                    # Close current section before this equipment listing
                    current_section_copy = current_section.copy()
                    current_section_copy['end_para'] = para_idx - 1

                    # Only add non-empty sections
                    if current_section_copy['start_para'] <= current_section_copy['end_para']:
                        sections.append(current_section_copy)

                    # Start new equipment section
                    current_section = equipment_info
                else:
                    # Continue with current section
                    current_section['content'].append(text)
                    current_section['end_para'] = para_idx
            else:
                # Add to current section content
                current_section['content'].append(text)
                current_section['end_para'] = para_idx

                # Check for subsections (2.1, 2.2, etc.)
                subsection_info = _detect_subsection(text, para_idx)
                if subsection_info:
                    if current_section:
                        current_section['end_para'] = para_idx - 1
                        sections.append(current_section)
                    current_section = subsection_info

                # Check for function lists starting with "обеспечивает:"
                elif "обеспечивает:" in text.lower():
                    # Create separate function description section
                    if current_section:
                        current_section['end_para'] = para_idx - 1
                        sections.append(current_section)

                    current_section = {
                        'start_para': para_idx,
                        'end_para': para_idx,
                        'content': [text],
                        'section_type': 'purpose',
                        'info_name': 'Описание функций изделия',
                        'description': 'Список функций, которые обеспечивает изделие',
                        'header': 'Список функций изделия'
                    }

    # Close final section
    if current_section:
        current_section['end_para'] = len(document.paragraphs) - 1
        sections.append(current_section)

    return sections


def _analyze_section_header(text: str, para_idx: int) -> Optional[Dict]:
    """Analyze section header and return section info."""
    text_lower = text.lower()

    # Section 1: Purpose/Purpose-related
    if any(keyword in text_lower for keyword in ['общие сведения', 'назначение', 'общее описание', '1.', '1 ']):
        return {
            'start_para': para_idx,
            'end_para': para_idx,
            'content': [text],
            'section_type': 'purpose',
            'info_name': 'Назначение',
            'description': 'Назначение и общие сведения о системе',
            'header': text
        }

    # Section 2: Device Description/Composition
    elif any(keyword in text_lower for keyword in ['состав', 'составные', 'оборудование', '2.', '2 ']):
        return {
            'start_para': para_idx,
            'end_para': para_idx,
            'content': [text],
            'section_type': 'description',
            'info_name': 'Описание',
            'description': 'Описание состава и оборудования системы',
            'header': text
        }

    # Section 3: Operation Principle/Information Exchange
    elif any(keyword in text_lower for keyword in ['информационный', 'принцип действия', 'работы', '3.', '3 ']):
        return {
            'start_para': para_idx,
            'end_para': para_idx,
            'content': [text],
            'section_type': 'operation',
            'info_name': 'Описание работы',
            'description': 'Описание принципа действия и информационного обмена',
            'header': text
        }

    # Check for component descriptions (блок, пульт, рама, etc.)
    elif _is_component_description(text_lower):
        return {
            'start_para': para_idx,
            'end_para': para_idx,
            'content': [text],
            'section_type': 'component',
            'info_name': text,  # Use component name as info_name
            'description': f'Описание компонента: {text}',
            'header': text,
            'is_component': True
        }

    return None


def _is_main_section_header(text: str) -> bool:
    """Check if text is a main section header (1., 2., 3., etc.)."""
    pattern = r'^\s*\d+\.?\s+'
    return bool(re.match(pattern, text))


def _detect_subsection(text: str, para_idx: int) -> Optional[Dict]:
    """Detect subsections like 2.1, 2.2, etc."""
    pattern = r'^\s*\d+\.\d+\s+'
    if re.match(pattern, text):
        return {
            'start_para': para_idx,
            'end_para': para_idx,
            'content': [text],
            'section_type': 'component',
            'info_name': text.strip(),  # Use subsection title as info_name
            'description': f'Описание компонента: {text.strip()}',
            'header': text.strip(),
            'is_component': True
        }
    return None


def _is_equipment_listing(text: str) -> bool:
    """Check if text is a standalone equipment listing that should be separated."""
    lower_text = text.lower().strip()

    # Specific patterns that indicate separate equipment items
    equipment_patterns = [
        r'^\d+\s*шт\.\s*-\s*.+',  # "2 шт. - description"
        r'^\d+\s*шт\.\s*адаптер', # "2 шт. адаптер..."
        r'^\d+\s*шт\.\s*в\s+',     # "2 шт. в location"
        r'^\d+\s*шт\.\s*блок',     # "2 шт. блок..."
        r'^\d+\s*шт\.\s*пульт',    # "2 шт. пульт..."
        r'^\d+\s*шт\.\s*преобразователь', # "2 шт. преобразователь..."
    ]

    for pattern in equipment_patterns:
        if re.search(pattern, lower_text, re.IGNORECASE):
            return True

    return False


def _create_equipment_section(text: str, para_idx: int) -> Optional[Dict]:
    """Create a separate component section for equipment listings."""
    # Extract meaningful name from equipment listing
    info_name = text.strip()

    # Clean up common patterns for better naming
    info_name = re.sub(r'^\d+\s*шт\.\s*-\s*', '', info_name)  # Remove "2 шт. - "
    info_name = re.sub(r'^\d+\s*шт\.\s*', '', info_name)     # Remove "2 шт. "

    return {
        'start_para': para_idx,
        'end_para': para_idx,
        'content': [text],
        'section_type': 'component',
        'info_name': info_name.strip(),  # Use cleaned equipment name as info_name
        'description': f'Описание оборудования: {text.strip()}',
        'header': text.strip(),
        'is_component': True,
        'is_equipment': True
    }


def _is_component_description(text: str) -> bool:
    """Check if text describes a component (block, unit, etc.) or equipment listing."""
    lower_text = text.lower()

    # Component keywords for hardware components
    component_keywords = [
        'блок', 'пульт', 'рама', 'система', 'контроллер', 'бусп', 'ски', 'бкп',
        'пусть', 'пнп', 'би-м', 'сброса', 'псо-5п', 'бус-5пм', 'рм-5п', 'рм-5пм',
        'рм-5п-1', 'пусть-5пм', 'бч-70', 'контроллер', 'кабель'
    ]

    # Equipment listing patterns (like "2 шт. - block name", "adapters", etc.)
    equipment_patterns = [
        r'^\d+\s*шт\.',  # "2 шт. ..."
        r'адаптер',      # adapters
        r'преобразователь', # converters
        r'усилитель',    # amplifiers
        r'индикатор',    # indicators
        r'выключатель',  # switches
        r'переключатель', # switches
        r'разъем',       # connectors
        r'кабель',       # cables
        r'датчик',       # sensors
        r'прибор',       # instruments
    ]

    # Check for explicit component keywords
    if any(keyword in lower_text for keyword in component_keywords):
        return True

    # Check for equipment listing patterns
    for pattern in equipment_patterns:
        if re.search(pattern, lower_text, re.IGNORECASE):
            return True

    return False


def generate_module_mapping_log(document_path: str, module_mapping: Dict[str, Dict], output_path: str) -> str:
    """
    Generate log file showing which sections are combined into which final modules.

    Args:
        document_path: Path to source document
        module_mapping: Dict mapping module filenames to module data
        output_path: Directory to save log file

    Returns:
        Path to generated log file
    """
    import os
    import datetime

    log_path = os.path.join(output_path, f"module_mapping_{os.path.basename(document_path).replace('.docx', '')}.log")

    with open(log_path, 'w', encoding='utf-8') as f:
        f.write("S1000D Module Mapping Log\n")
        f.write(f"Generated: {datetime.datetime.now()}\n")
        f.write(f"Source file: {document_path}\n")
        f.write("=" * 80 + "\n\n")

        for filename, module_data in module_mapping.items():
            dm_code = module_data['dm_code']
            sections = module_data['sections']

            f.write(f"Module: {filename}\n")
            f.write(f"  DM Code: {dm_code}\n")
            f.write(f"  info_name: {module_data.get('info_name', 'Unknown')}\n")
            f.write(f"  Section count: {len(sections)}\n")
            f.write(f"  Combined content lines: {sum(len(s.get('content', [])) for s in sections)}\n")
            f.write("\n")
            f.write("  Contained sections:\n")

            for i, section in enumerate(sections):
                f.write(f"    {i+1}. Section '{section.get('header', 'No header')}'\n")
                f.write(f"        Type: {section.get('section_type', 'Unknown')}\n")
                f.write(f"        Paragraph range: {section.get('start_para', '?')} - {section.get('end_para', '?')}\n")
                f.write(f"        Description: {section.get('description', 'No description')}\n")
                if section.get('is_component'):
                    f.write(f"        Component: Yes\n")
                f.write("\n")

            f.write("  Content preview (first 5 lines from first section):\n")
            if sections and sections[0].get('content'):
                for j, line in enumerate(sections[0]['content'][:5]):
                    f.write(f"    {j+1}: {line[:100]}{'...' if len(line) > 100 else ''}\n")
            f.write("\n" + "-" * 80 + "\n\n")

    print(f"Module mapping log saved to: {log_path}")
    return log_path


def generate_content_analysis_log(document_path: str, analysis_results: List[Dict], output_path: str, module_mapping: Dict[str, List[Dict]] = None) -> str:
    """
    Generate log file with content analysis results.

    Args:
        document_path: Path to source document
        analysis_results: List of analyzed sections
        output_path: Directory to save log file

    Returns:
        Path to generated log file
    """
    import os
    import datetime

    log_path = os.path.join(output_path, f"content_analysis_{os.path.basename(document_path).replace('.docx', '')}.log")

    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f"Content Analysis Log\n")
        f.write(f"Generated: {datetime.datetime.now()}\n")
        f.write(f"Source file: {document_path}\n")
        f.write("=" * 80 + "\n\n")

        for i, section in enumerate(analysis_results):
            f.write(f"Section {i+1}:\n")
            f.write(f"  info_name: {section.get('info_name', 'Unknown')}\n")
            f.write(f"  description: {section.get('description', 'No description')}\n")
            f.write(f"  section_type: {section.get('section_type', 'Unknown')}\n")
            f.write(f"  start_reference: paragraph {section.get('start_para', 'Unknown')}\n")
            f.write(f"  end_reference: paragraph {section.get('end_para', 'Unknown')}\n")
            f.write(f"  header: {section.get('header', 'No header')}\n")
            f.write(f"  content_lines: {len(section.get('content', []))}\n")
            if section.get('is_component'):
                f.write("  is_component: Yes\n")
            f.write("\n")
            f.write("  Content preview:\n")
            for j, line in enumerate(section.get('content', [])[:3]):  # First 3 lines
                f.write(f"    {j+1}: {line[:100]}{'...' if len(line) > 100 else ''}\n")
            f.write("\n" + "-" * 80 + "\n\n")

    print(f"Content analysis log saved to: {log_path}")
    return log_path


def get_content_for_info_name(analysis_results: List[Dict], info_name: str) -> List[Dict]:
    """
    Get content sections for a specific info_name value.

    Args:
        analysis_results: Results from analyze_document_content
        info_name: Target info_name value

    Returns:
        List of content sections for this info_name
    """
    return [section for section in analysis_results if section.get('info_name') == info_name]
