"""
Descriptive module processor.
Orchestrates parsing, maps sections to infoCodes, and generates multiple XML files.
"""

import os
import re
from typing import Dict, List
from docx import Document

# Import parser modules
from parsers.text_parser import extract_text_by_headings, get_document_structure
from parsers.table_parser import get_tables_by_reference
from parsers.list_parser import extract_lists, convert_list_to_s1000d_randomlist
from parsers.illustration_parser import extract_illustrations, find_image_references, map_figures_to_illustrations

# Import generator
from generators.s1000d_generator import S1000DGenerator, create_data_module_config


def extract_document_title(document: Document) -> str:
    """
    Extract main title from the first page/document header.

    Args:
        document: Word document object

    Returns:
        Document title or default if not found
    """
    # First try to get from the first paragraph (document title often has Normal style)
    for para in document.paragraphs:
        text = para.text.strip()
        if text and not para.style.name.startswith('Heading'):  # Skip headings, look for title
            # Check if it looks like a title with dash
            if "–" in text:
                return text.split("–")[0].strip()
            elif "-" in text:
                return text.split("-")[0].strip()
            # If it has multiple words and is long, might be title
            if len(text) > 20:
                return text.strip()

    # Fallback: get from headings if above didn't work
    headings = get_document_structure(document)
    if headings:
        first_heading = headings[0].strip()
        # Parse the part before "–" or "-"
        if "–" in first_heading:
            return first_heading.split("–")[0].strip()
        elif "-" in first_heading:
            return first_heading.split("-")[0].strip()

    # Ultimate fallback
    return "Система"


def extract_organization_from_document(document: Document) -> str:
    """
    Extract organization name from document headers and footers.

    Args:
        document: Word document object

    Returns:
        Organization name or "Организация не задана" if not found
    """
    text = ""

    # Check all sections' headers and footers
    for section in document.sections:
        # Get header text - headers can have different types (first_page, even_page, odd_page)
        if hasattr(section.header, 'is_linked_to_previous') and not section.header.is_linked_to_previous:
            # Only add if not linked to avoid duplication
            for paragraph in section.header.paragraphs:
                text += paragraph.text + " "

        # Get footer text
        if hasattr(section.footer, 'is_linked_to_previous') and not section.footer.is_linked_to_previous:
            for paragraph in section.footer.paragraphs:
                text += paragraph.text + " "

    # Regex to find organization: abbreviation + nearest word after it
    pattern = r'(?:ОКБ|КБ|АО|ООО|НИЦ)\s*([^\s]+)'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        abbreviation = match.group(0).replace(match.group(1), '').strip()
        word_after = match.group(1).strip()
        return f"{abbreviation} {word_after}"
    else:
        return "Организация не задана"


def map_heading_to_info_code(heading: str, component_index: int = 0) -> Dict:
    """
    Map document heading to S1000D infoCode.

    Args:
        heading: Document heading text
        component_index: Index for component numbering

    Returns:
        Dict with DM code components
    """
    heading_lower = heading.lower()

    base_dm_code = {
        'modelIdentCode': 'S5',
        'systemDiffCode': 'A',
        'systemCode': '120',
        'subSystemCode': '1',  # RSOO subsystem
        'subSubSystemCode': '0',
        'assyCode': '00',
        'disassyCode': '00',
        'disassyCodeVariant': 'A',
        'infoCode': '011',
        'infoCodeVariant': 'A',
        'itemLocationCode': 'A'
    }

    # System level modules
    if 'общие сведения' in heading_lower:
        base_dm_code.update({'infoCode': '011', 'infoCodeVariant': 'A'})  # Purpose
        return base_dm_code
    elif 'состав рсуо' in heading_lower or 'оборудовани' in heading_lower:
        base_dm_code.update({'infoCode': '012', 'infoCodeVariant': 'A'})  # Description
        return base_dm_code
    elif 'структурно представляет' in heading_lower:
        base_dm_code.update({'infoCode': '013', 'infoCodeVariant': 'A'})  # Operation structure
        return base_dm_code
    elif 'информацион' in heading_lower:
        base_dm_code.update({'infoCode': '014', 'infoCodeVariant': 'A'})  # Info exchange
        return base_dm_code
    elif 'режимы работы' in heading_lower:
        base_dm_code.update({'infoCode': '013', 'infoCodeVariant': 'A'})  # General operation
        return base_dm_code
    elif 'автомати' in heading_lower in heading_lower:
        base_dm_code.update({'infoCode': '015', 'infoCodeVariant': 'A'})  # Automatic mode
        return base_dm_code
    elif 'автоном' in heading_lower in heading_lower:
        base_dm_code.update({'infoCode': '015', 'infoCodeVariant': 'B'})  # Autonomous mode
        return base_dm_code
    elif 'аварийн' in heading_lower in heading_lower:
        base_dm_code.update({'infoCode': '015', 'infoCodeVariant': 'C'})  # Emergency mode
        return base_dm_code
    elif 'учебно' in heading_lower in heading_lower:
        base_dm_code.update({'infoCode': '015', 'infoCodeVariant': 'D'})  # Training mode
        return base_dm_code
    elif 'управлени' in heading_lower and ('створками' in heading_lower or 'платформ' in heading_lower):
        base_dm_code.update({'infoCode': '016', 'infoCodeVariant': 'A'})  # Additional operations
        return base_dm_code
    else:
        # Check if it's a component (equipment, unit, block, etc.)
        unit_keywords = ['блок', 'пульт', 'рама', 'система', 'блокировка', 'контроллер', 'бусп', 'ски', 'бкп', 'пусть', 'пнп', 'би-м', 'сброса', 'псо-5п', 'бус-5пм', 'рм-5п', 'рм-5пм', 'рм-5п-1', 'пусть-5пм', 'бч-70']
        if any(keyword in heading_lower for keyword in unit_keywords):
            # Component description
            base_dm_code.update({
                'subSubSystemCode': f'{component_index % 10}',
                'infoCode': '017',
                'infoCodeVariant': 'A'
            })
            return base_dm_code

    # Default to description
    base_dm_code.update({'infoCode': '012'})
    return base_dm_code


def process_descriptive_document(doc_path: str, output_dir: str):
    """
    Process descriptive document: orchestrate parsing, map sections, generate XML files.

    Args:
        doc_path: Path to docx document
        output_dir: Output directory for generated files
    """
    print(f"Processing descriptive document: {doc_path}")

    # Load document
    doc = Document(doc_path)

    # Extract organization from headers/footers
    organization = extract_organization_from_document(doc)
    print(f"Extracted organization: {organization}")

    # Extract document title
    document_title = extract_document_title(doc)
    print(f"Extracted document title: {document_title}")

    # Parse document content
    print("Parsing document content...")
    headings = get_document_structure(doc)
    text_sections = extract_text_by_headings(doc)
    tables = get_tables_by_reference(doc)
    lists_data = extract_lists(doc)
    illustrations = extract_illustrations(doc, output_dir)

    print(f"Found {len(headings)} sections, {len(tables)} tables, {len(lists_data)} lists, {len(illustrations)} illustrations")

    # Initialize generator
    generator = S1000DGenerator()

    # Process each section and create data modules
    generated_files = []
    component_counter = 1

    section_groups = group_sections_by_type(headings)

    for group_type, section_indices in section_groups.items():
        if group_type == "system_purpose":
            # Module for purpose
            purpose_sections = [headings[i] for i in section_indices]
            content = assemble_content(purpose_sections, text_sections, tables, lists_data)
            dm_code = map_heading_to_info_code(purpose_sections[0])
            dm_config = create_data_module_config(
                document_title,
                "Назначение",
                dm_code,
                content,
                enterprise_name=organization,
                originator_name=organization
            )
            filepath = generator.generate_data_module(dm_config, output_dir)
            generated_files.append(filepath)

        elif group_type == "system_description":
            # Module for composition and equipment
            desc_sections = [headings[i] for i in section_indices]
            content = assemble_content(desc_sections, text_sections, tables, lists_data)
            dm_code = map_heading_to_info_code(desc_sections[0])
            dm_config = create_data_module_config(
                document_title,
                "Описание",
                dm_code,
                content,
                enterprise_name=organization,
                originator_name=organization
            )
            filepath = generator.generate_data_module(dm_config, output_dir)
            generated_files.append(filepath)

        elif group_type == "system_operation":
            # Module for operation
            oper_sections = [headings[i] for i in section_indices]
            content = assemble_content(oper_sections, text_sections, tables, lists_data)
            dm_code = map_heading_to_info_code(oper_sections[0])
            dm_config = create_data_module_config(
                document_title,
                "Описание работы",
                dm_code,
                content,
                enterprise_name=organization,
                originator_name=organization
            )
            filepath = generator.generate_data_module(dm_config, output_dir)
            generated_files.append(filepath)

        elif group_type == "components":
            # Individual module for each component
            for i in section_indices:
                heading = headings[i]
                content = assemble_content([heading], text_sections, tables, lists_data)
                dm_code = map_heading_to_info_code(heading, component_counter)
                # Use component name as techName, keep the system name consistent
                dm_config = create_data_module_config(
                    document_title,
                    heading,
                    dm_code,
                    content,
                    enterprise_name=organization,
                    originator_name=organization
                )
                filepath = generator.generate_data_module(dm_config, output_dir)
                generated_files.append(filepath)
                component_counter += 1

    print(f"Generated {len(generated_files)} data module files:")
    for filepath in generated_files:
        print(f"  - {os.path.basename(filepath)}")

    return generated_files


def group_sections_by_type(headings: List[str]) -> Dict[str, List[int]]:
    """
    Group section indices by their type for data module creation.

    Args:
        headings: List of section headings

    Returns:
        Dict mapping group types to lists of section indices
    """
    groups = {
        "system_purpose": [],
        "system_description": [],
        "system_operation": [],
        "components": []
    }

    for idx, heading in enumerate(headings):
        heading_lower = heading.lower()

        if 'общие сведения' in heading_lower:
            groups["system_purpose"].append(idx)
        elif 'состав рсуо' in heading_lower or 'оборудовани' in heading_lower or 'структурно представляет' in heading_lower:
            groups["system_description"].append(idx)
        elif 'информацион' in heading_lower or 'режимы работы' in heading_lower or 'управлени' in heading_lower:
            groups["system_operation"].append(idx)
        else:
            # Check if component
            unit_keywords = ['блок', 'пульт', 'рама', 'система', 'контроллер', 'бусп', 'ски', 'бкп', 'пусть', 'пнп', 'би-м', 'сброса', 'псо-5п', 'бус-5пм', 'бч-70']
            if any(keyword in heading_lower for keyword in unit_keywords):
                groups["components"].append(idx)

    return groups


def assemble_content(sections: List[str], text_sections: Dict[str, str], tables: Dict[str, Dict], lists_data: List[Dict]) -> Dict:
    """
    Assemble content from parsed sections.

    Args:
        sections: List of section headings to include
        text_sections: Dict of heading -> text content
        tables: Dict of table references
        lists_data: List of parsed lists

    Returns:
        Content dict with paragraphs, tables, lists
    """
    content = {
        "paragraphs": [],
        "tables": [],
        "lists": []
    }

    # Add paragraphs from sections
    for section in sections:
        if section in text_sections:
            # Split by paragraphs and add
            paras = text_sections[section].split('\n')
            content["paragraphs"].extend([p.strip() for p in paras if p.strip()])

    # Add lists (for now, convert all lists - could be enhanced to map to sections)
    for list_data in lists_data:
        if list_data.get('items'):
            list_xml = convert_list_to_s1000d_randomlist(list_data)
            content["lists"].append(list_xml)

    # Add tables (simplified - add them all)
    from parsers.table_parser import convert_table_to_s1000d_format
    for table_ref, table_data in tables.items():
        table_xml = convert_table_to_s1000d_format(table_data)
        content["tables"].append(table_xml)

    return content
