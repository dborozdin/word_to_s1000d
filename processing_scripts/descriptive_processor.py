"""
Descriptive module processor.
Orchestrate parsing, maps sections to infoCodes, and generates multiple XML files.
"""

import os
import re
import configparser
from typing import Dict, List
from docx import Document

# Import parser modules
from parsers.text_parser import extract_text_by_headings, get_document_structure
from parsers.table_parser import get_tables_by_reference
from parsers.list_parser import extract_lists, convert_list_to_s1000d_randomlist
from parsers.illustration_parser import extract_illustrations, find_image_references, map_figures_to_illustrations
from parsers.content_analyzer import analyze_document_content, generate_content_analysis_log, get_content_for_info_name

# Import generators
from generators.s1000d_generator import S1000DGenerator, create_data_module_config
from generators.pm_generator import PMGenerator, create_pm_config, create_dm_ref_data


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

    # Read configuration
    config = configparser.ConfigParser()
    config.read('config.ini')
    split_into_modules = config.getboolean('processing', 'split_into_modules', fallback=False)
    print(f"Split into modules: {split_into_modules}")

    # Load document
    doc = Document(doc_path)

    # Extract organization from headers/footers
    organization = extract_organization_from_document(doc)
    print(f"Extracted organization: {organization}")

    # Extract document title
    document_title = extract_document_title(doc)
    print(f"Extracted document title: {document_title}")

    # Analyze document content using the new content analyzer
    print("Analyzing document content structure...")
    analysis_results = analyze_document_content(doc)

    # Generate content analysis log
    log_path = generate_content_analysis_log(doc_path, analysis_results, output_dir)

    # Parse additional content types
    print("Parsing additional content...")
    text_sections = extract_text_by_headings(doc)
    tables = get_tables_by_reference(doc)
    lists_data = extract_lists(doc)
    illustrations = extract_illustrations(doc, output_dir)

    print(f"Found {len(analysis_results)} analyzed sections, {len(tables)} tables, {len(lists_data)} lists, {len(illustrations)} illustrations")

    # Initialize generator
    generator = S1000DGenerator()
    pm_generator = PMGenerator()

    # Generate data modules based on content analysis
    generated_files = []
    dm_refs = []  # List to collect DM references for PM
    component_counter = 0

    # Track mapping of sections to modules for logging
    module_mapping = {}  # filename -> module_data

    # Group sections by their unique characteristics for module generation
    section_groups = group_sections_for_modules(analysis_results, split_into_modules)

    for group_key, group_info in section_groups.items():
        sections_in_group = group_info['sections']

        # Choose representative section for DM code generation (first one)
        representative_section = sections_in_group[0]

        # Prepare combined content for this module
        combined_content = {
            "paragraphs": [],
            "tables": [],
            "lists": []
        }

        # Combine content from all sections in this group
        for section in sections_in_group:
            section_content = assemble_content_for_section(section, doc, tables, lists_data)
            combined_content["paragraphs"].extend(section_content["paragraphs"])
            combined_content["lists"].extend(section_content["lists"])

        # Add all tables
        for table_ref, table_data in tables.items():
            from parsers.table_parser import convert_table_to_s1000d_format
            table_xml = convert_table_to_s1000d_format(table_data)
            combined_content["tables"].append(table_xml)

        # Determine DM code based on section type
        dm_code = get_dm_code_for_section(representative_section, component_counter)

        # Map section type to appropriate module type
        if representative_section.get('section_type') == 'purpose':
            if representative_section.get('info_name') == 'Описание функций изделия':
                dm_code.update({'infoCode': '012', 'infoCodeVariant': 'B'})  # Function description
            else:
                dm_code.update({'infoCode': '011', 'infoCodeVariant': 'A'})  # General purpose
        elif representative_section.get('section_type') == 'description':
            dm_code.update({'infoCode': '012', 'infoCodeVariant': 'A'})  # Description
        elif representative_section.get('section_type') == 'operation':
            dm_code.update({'infoCode': '013', 'infoCodeVariant': 'A'})  # Operation
        elif representative_section.get('section_type') == 'component':
            dm_code.update({'infoCode': '017', 'infoCodeVariant': 'A'})  # Component description
            component_counter += 1

        # Create DM config
        dm_config = create_data_module_config(
            document_title,
            representative_section.get('info_name', 'Неопределен'),
            dm_code,
            combined_content,
            enterprise_name=organization,
            originator_name=organization
        )

        # Generate XML file
        filepath = generator.generate_data_module(dm_config, output_dir)
        generated_files.append(filepath)

        # Collect DM ref for PM generation
        dm_ref = create_dm_ref_data(
            dm_code,
            document_title,  # techName
            representative_section.get('info_name', 'Неопределен')  # infoName
        )
        dm_refs.append(dm_ref)

        # Track mapping for logging
        filename = os.path.basename(filepath)
        module_mapping[filename] = {
            'dm_code': dm_code_to_string(dm_code),
            'info_name': representative_section.get('info_name', 'Unknown'),
            'sections': sections_in_group
        }

        print(f"Generated module: {representative_section.get('info_name', 'Unknown')} -> {filename}")

    # Generate module mapping log
    from parsers.content_analyzer import generate_module_mapping_log
    mapping_log_path = generate_module_mapping_log(doc_path, module_mapping, output_dir)

    # Generate Publication Module (PMC)
    if dm_refs:
        # Use fixed modelIdentCode from first DM or extract short code
        first_dm = dm_refs[0] if dm_refs else None
        model_code = first_dm['dm_code'].get('modelIdentCode', 'S5') if first_dm else 'S5'
        pm_config = create_pm_config(
            model_ident_code=model_code,
            pm_title=document_title,
            enterprise_name=organization,
            originator_name=organization
        )
        pm_filepath = pm_generator.generate_publication_module(pm_config, dm_refs, output_dir)
        generated_files.append(pm_filepath)
        print(f"Generated publication module: {os.path.basename(pm_filepath)}")

    print(f"\nGenerated {len(generated_files)} files:")
    for filepath in generated_files:
        print(f"  - {os.path.basename(filepath)}")

    print(f"Content analysis log: {os.path.basename(log_path)}")
    print(f"Module mapping log: {os.path.basename(mapping_log_path)}")

    return generated_files


def group_sections_for_modules(analysis_results: List[Dict], split_into_modules: bool) -> Dict[str, Dict]:
    """
    Group sections that should be combined into the same module.

    Args:
        analysis_results: Results from analyze_document_content
        split_into_modules: Whether to split into multiple modules or combine into one

    Returns:
        Dict mapping group keys to group info with sections
    """
    if not split_into_modules:
        # Combine all sections into a single module
        all_info_names = [section.get('info_name', 'unknown') for section in analysis_results]
        combined_info_name = ', '.join(set(all_info_names)) if all_info_names else 'Combined document'
        return {
            'combined': {
                'sections': analysis_results,
                'info_name': combined_info_name
            }
        }

    # Original logic: split into multiple modules
    groups = {}

    for section in analysis_results:
        section_type = section.get('section_type', 'unknown')
        info_name = section.get('info_name', 'unknown')

        if section_type == 'component':
            # Each component gets its own module
            group_key = f"component_{section.get('start_para', 0)}"
        elif info_name == 'Описание функций изделия':
            # Function descriptions get their own module
            group_key = "function_description"
        elif section_type in ['purpose', 'description', 'operation']:
            # Group sections of same type together (not ideal, but better than duplicates)
            group_key = f"{section_type}_{info_name.replace(' ', '_')}"
        else:
            # Fallback grouping
            group_key = f"misc_{section.get('start_para', 0)}"

        if group_key not in groups:
            groups[group_key] = {
                'sections': [],
                'info_name': info_name
            }

        groups[group_key]['sections'].append(section)

    return groups


def dm_code_to_string(dm_code: Dict) -> str:
    """Convert DM code dict to string representation."""
    return "DMC-S5-A-120-{system_sub}-{sub_sub}-{assy}-{disassy}{disassy_var}-{info}{info_var}-{location}_001".format(
        system_sub=dm_code.get('subSystemCode', '1'),
        sub_sub=dm_code.get('subSubSystemCode', '0'),
        assy=dm_code.get('assyCode', '00'),
        disassy=dm_code.get('disassyCode', '00'),
        disassy_var=dm_code.get('disassyCodeVariant', 'A'),
        info=dm_code.get('infoCode', '011'),
        info_var=dm_code.get('infoCodeVariant', 'A'),
        location=dm_code.get('itemLocationCode', 'A')
    )


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


def assemble_content_for_section(section: Dict, document: Document, tables: Dict[str, Dict], lists_data: List[Dict]) -> Dict:
    """
    Assemble content for a specific analyzed section.

    Args:
        section: Section dictionary from content analysis
        document: Document object
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

    # Extract content from the section's paragraph range
    start_para = section.get('start_para', 0)
    end_para = section.get('end_para', len(document.paragraphs) - 1)

    for para_idx in range(start_para, min(end_para + 1, len(document.paragraphs))):
        para = document.paragraphs[para_idx]
        text = para.text.strip()
        if text:
            content["paragraphs"].append(text)

    # Add relevant lists (simplified - add all for now)
    for list_data in lists_data:
        if list_data.get('items'):
            list_xml = convert_list_to_s1000d_randomlist(list_data)
            content["lists"].append(list_xml)

    # Add relevant tables (simplified - add all for now)
    from parsers.table_parser import convert_table_to_s1000d_format
    for table_ref, table_data in tables.items():
        table_xml = convert_table_to_s1000d_format(table_data)
        content["tables"].append(table_xml)

    return content


def get_dm_code_for_section(section: Dict, component_counter: int) -> Dict:
    """
    Get DM code for a section based on its type and index.

    Args:
        section: Section dictionary from content analysis
        component_counter: Counter for component numbering

    Returns:
        DM code dictionary
    """
    base_dm_code = {
        'modelIdentCode': 'S5',
        'systemDiffCode': 'A',
        'systemCode': '120',
        'subSystemCode': '1',
        'subSubSystemCode': '0',
        'assyCode': '00',
        'disassyCode': '00',
        'disassyCodeVariant': 'A',
        'infoCode': '011',
        'infoCodeVariant': 'A',
        'itemLocationCode': 'A'
    }

    if section.get('is_component'):
        # Component-specific coding
        base_dm_code.update({
            'subSubSystemCode': f'{component_counter}',
            'infoCode': '017',
            'infoCodeVariant': 'A'
        })

    return base_dm_code


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
