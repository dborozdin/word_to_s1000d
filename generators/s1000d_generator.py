"""
S1000D XML generator.
Creates ASD S1000D data module XML files.
"""

import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from lxml import etree as ET


class S1000DGenerator:
    """Generator for S1000D data modules."""

    def __init__(self, model_ident: str = "S5", system_diff: str = "A"):
        """
        Initialize generator with base parameters.

        Args:
            model_ident: Model identifier code
            system_diff: System difference code
        """
        self.model_ident = model_ident
        self.system_diff = system_diff

    def _create_base_xml_structure(self, schema_type: str = "descript") -> ET.Element:
        """Create basic dmodule element with namespaces.

        Args:
            schema_type: 'descript' or 'proced' to select the XSD schema reference.
        """
        schema_urls = {
            "descript": "http://www.s1000d.org/S1000D_4-1/xml_schema_flat/descript.xsd",
            "proced": "http://www.s1000d.org/S1000D_4-1/xml_schema_flat/proced.xsd",
        }
        schema_url = schema_urls.get(schema_type, schema_urls["descript"])

        xml_str = f'''<dmodule xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                      xsi:noNamespaceSchemaLocation="{schema_url}"
                      xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                      xmlns:dc="http://www.purl.org/dc/elements/1.1/"
                      xmlns:xlink="http://www.w3.org/1999/xlink">
        </dmodule>'''

        dmodule = ET.fromstring(xml_str)
        return dmodule

    def _create_ident_and_status_section(self, dm_code_components: Dict, title_data: Dict) -> ET.Element:
        """Create identAndStatusSection."""
        section = ET.Element("identAndStatusSection")

        dm_address = ET.SubElement(section, "dmAddress")
        dm_ident = ET.SubElement(dm_address, "dmIdent")

        # Build dmCode
        dm_code = ET.SubElement(dm_ident, "dmCode",
                               modelIdentCode=dm_code_components.get('modelIdentCode', self.model_ident),
                               systemDiffCode=dm_code_components.get('systemDiffCode', self.system_diff),
                               systemCode=dm_code_components.get('systemCode'),
                               subSystemCode=dm_code_components.get('subSystemCode'),
                               subSubSystemCode=dm_code_components.get('subSubSystemCode'),
                               assyCode=dm_code_components.get('assyCode'),
                               disassyCode=dm_code_components.get('disassyCode'),
                               disassyCodeVariant=dm_code_components.get('disassyCodeVariant'),
                               infoCode=dm_code_components.get('infoCode'),
                               infoCodeVariant=dm_code_components.get('infoCodeVariant'),
                               itemLocationCode=dm_code_components.get('itemLocationCode'))

        # Language and issue
        lang_elem = ET.SubElement(dm_ident, "language", languageIsoCode="ru", countryIsoCode="RU")
        issue_elem = ET.SubElement(dm_ident, "issueInfo", issueNumber="001", inWork="00")

        # Address items
        dm_address_items = ET.SubElement(dm_address, "dmAddressItems")
        issue_date = ET.SubElement(dm_address_items, "issueDate",
                                  year=str(datetime.now().year),
                                  month=str(datetime.now().month).zfill(2),
                                  day=str(datetime.now().day).zfill(2))

        # Title
        dm_title = ET.SubElement(dm_address_items, "dmTitle")
        tech_name = ET.SubElement(dm_title, "techName")
        tech_name.text = title_data.get('techName', '')

        info_name = ET.SubElement(dm_title, "infoName")
        info_name.text = title_data.get('infoName', '')

        # dmStatus
        dm_status = ET.SubElement(section, "dmStatus", issueType="new")

        security = ET.SubElement(dm_status, "security", securityClassification="01")

        logo = ET.SubElement(dm_status, "logo")
        symbol = ET.SubElement(logo, "symbol", infoEntityIdent="PUBLICATION_LOGO")

        responsible_company = ET.SubElement(dm_status, "responsiblePartnerCompany", enterpriseCode="00000")
        enterprise_name = ET.SubElement(responsible_company, "enterpriseName")
        enterprise_name.text = title_data.get('enterpriseName', "Организация не задана")

        originator = ET.SubElement(dm_status, "originator", enterpriseCode="00000")
        originator_name = ET.SubElement(originator, "enterpriseName")
        originator_name.text = title_data.get('originatorName', "Организация не задана")

        applic = ET.SubElement(dm_status, "applic")
        display_text = ET.SubElement(applic, "displayText")
        simple_para = ET.SubElement(display_text, "simplePara")
        simple_para.text = "Все"

        tech_standard = ET.SubElement(dm_status, "techStandard")
        tech_pub_base = ET.SubElement(tech_standard, "techPubBase")
        tech_pub_base.text = "AECMA 1000D / AC 1.1.S1000DR-2007"

        EA_exceptions = ET.SubElement(tech_standard, "authorityExceptions")
        EA_notes = ET.SubElement(tech_standard, "authorityNotes")

        # BREX reference
        brex_dm_ref = ET.SubElement(dm_status, "brexDmRef")
        dm_ref = ET.SubElement(brex_dm_ref, "dmRef")
        dm_ref_ident = ET.SubElement(dm_ref, "dmRefIdent")
        brex_dm_code = ET.SubElement(dm_ref_ident, "dmCode",
                                    modelIdentCode=self.model_ident,
                                    systemDiffCode=self.system_diff,
                                    systemCode="00",
                                    subSystemCode="0",
                                    subSubSystemCode="0",
                                    assyCode="00",
                                    disassyCode="00",
                                    disassyCodeVariant="A",
                                    infoCode="022",
                                    infoCodeVariant="A",
                                    itemLocationCode="D")

        quality_assurance = ET.SubElement(dm_status, "qualityAssurance")
        unverified = ET.SubElement(quality_assurance, "unverified")

        return section

    def _create_content_section(self, content_data: Dict, figure_info: List = None) -> ET.Element:
        """Create content section."""
        content = ET.Element("content")
        description = ET.SubElement(content, "description")

        # Track unique IDs for figures and graphics
        figure_id_counter = 1
        graphic_id_counter = 1

        # If xml_parts are provided, process them according to S1000D structure
        if 'xml_parts' in content_data:
            current_levelled_para = None

            for xml_part in content_data['xml_parts']:
                if xml_part.strip():
                    try:
                        part_elem = ET.fromstring(xml_part)

                        # Handle different element types according to S1000D schema
                        if part_elem.tag == 'levelledPara':
                            # levelledPara can be direct child of description
                            description.append(part_elem)
                            current_levelled_para = part_elem
                        elif part_elem.tag == 'para':
                            # para elements should be wrapped in levelledPara if not already in one
                            if current_levelled_para is None:
                                current_levelled_para = ET.SubElement(description, "levelledPara")
                            current_levelled_para.append(part_elem)
                        elif part_elem.tag == 'table':
                            # Fix table entries to wrap text in <para>
                            for entry in part_elem.iter('entry'):
                                if entry.text and entry.text.strip():
                                    para_elem = ET.SubElement(entry, "para")
                                    para_elem.text = entry.text
                                    entry.text = None
                            # Add table to current levelledPara if exists, otherwise to description
                            if current_levelled_para is not None:
                                current_levelled_para.append(part_elem)
                            else:
                                description.append(part_elem)
                            # Don't reset current_levelled_para - keep adding to same section
                        elif part_elem.tag == 'randomList':
                            # Add list to current levelledPara if exists, otherwise to description
                            if current_levelled_para is not None:
                                current_levelled_para.append(part_elem)
                            else:
                                description.append(part_elem)
                            # Don't reset current_levelled_para - keep adding to same section
                        elif part_elem.tag == 'figure':
                            # Fix figure and graphic IDs to be unique
                            figure_elem = part_elem
                            figure_elem.set('id', f'fig{figure_id_counter}')
                            for graphic in figure_elem:
                                if graphic.tag == 'graphic':
                                    graphic.set('id', f'gra{figure_id_counter}')
                                    figure_id_counter += 1
                                    break
                            # Add figure to current levelledPara if exists, otherwise to description
                            if current_levelled_para is not None:
                                current_levelled_para.append(figure_elem)
                            else:
                                description.append(figure_elem)
                            # Don't reset current_levelled_para - keep adding to same section
                        elif part_elem.tag == 'warning':
                            # Convert any <para> inside warning to <warningAndCautionPara>
                            for para in part_elem.xpath('.//para'):
                                para.tag = 'warningAndCautionPara'
                            # Add warning to current levelledPara if exists, otherwise to description
                            if current_levelled_para is not None:
                                current_levelled_para.append(part_elem)
                            else:
                                description.append(part_elem)
                            # Don't reset current_levelled_para - keep adding to same section
                        else:
                            # For other elements, try to add them appropriately
                            if current_levelled_para is None:
                                current_levelled_para = ET.SubElement(description, "levelledPara")
                            current_levelled_para.append(part_elem)

                    except ET.ParseError:
                        # If parsing fails, add as text in para within levelledPara
                        if current_levelled_para is None:
                            current_levelled_para = ET.SubElement(description, "levelledPara")
                        para_elem = ET.SubElement(current_levelled_para, "para")
                        para_elem.text = xml_part
        else:
            # Legacy mode: wrap everything in levelledPara
            levelled_para = ET.SubElement(description, "levelledPara")

            # Add paragraphs
            for para_text in content_data.get('paragraphs', []):
                if para_text.strip():
                    para_elem = ET.SubElement(levelled_para, "para")
                    para_elem.text = para_text

            # Add tables
            for table_xml in content_data.get('tables', []):
                if table_xml:
                    # Parse and add table element
                    table_elem = ET.fromstring(table_xml)
                    # Fix table entries to wrap text in <para>
                    for entry in table_elem.iter('entry'):
                        if entry.text and entry.text.strip():
                            para_elem = ET.SubElement(entry, "para")
                            para_elem.text = entry.text
                            entry.text = None
                    description.append(table_elem)  # Tables go directly to description

            # Add lists
            for list_xml in content_data.get('lists', []):
                if list_xml:
                    # Lists are direct children of description
                    list_elem = ET.fromstring(list_xml)
                    description.append(list_elem)  # Lists go directly to description

        return content

    # ------------------------------------------------------------------
    # Procedure module generation
    # ------------------------------------------------------------------

    def _create_procedure_content_section(self, procedure_data: Dict) -> ET.Element:
        """Create content section with <procedure> element for proced.xsd modules."""
        content = ET.Element("content")
        procedure = ET.SubElement(content, "procedure")

        # 1. preliminaryRqmts (required)
        prelim = ET.SubElement(procedure, "preliminaryRqmts")
        self._build_prelim_rqmts(prelim, procedure_data.get('preliminary_rqmts', {}))

        # 2. mainProcedure (required)
        main_proc = ET.SubElement(procedure, "mainProcedure")
        self._build_procedural_steps(main_proc, procedure_data.get('procedural_steps', []))

        # 3. closeRqmts (required)
        close = ET.SubElement(procedure, "closeRqmts")
        req_cond_group = ET.SubElement(close, "reqCondGroup")
        ET.SubElement(req_cond_group, "noConds")

        return content

    def _build_prelim_rqmts(self, parent: ET.Element, data: Dict):
        """Build preliminaryRqmts children."""
        # reqCondGroup
        req_cond_group = ET.SubElement(parent, "reqCondGroup")
        ET.SubElement(req_cond_group, "noConds")

        # reqSupportEquips
        support_equips = data.get('support_equips', [])
        req_support = ET.SubElement(parent, "reqSupportEquips")
        if support_equips:
            group = ET.SubElement(req_support, "supportEquipDescrGroup")
            for idx, item in enumerate(support_equips):
                descr = ET.SubElement(group, "supportEquipDescr", id=f"seq-{idx:04d}")
                name_elem = ET.SubElement(descr, "name")
                name_elem.text = item.get('name', '') if isinstance(item, dict) else str(item)
                ident_num = ET.SubElement(descr, "identNumber")
                ET.SubElement(ident_num, "manufacturerCode")
                qty = ET.SubElement(descr, "reqQuantity")
                qty.text = "По требованию"
        else:
            ET.SubElement(req_support, "noSupportEquips")

        # reqSupplies
        supplies = data.get('supplies', [])
        req_supplies = ET.SubElement(parent, "reqSupplies")
        if supplies:
            group = ET.SubElement(req_supplies, "supplyDescrGroup")
            for idx, item in enumerate(supplies):
                descr = ET.SubElement(group, "supplyDescr", id=f"sup-{idx:04d}")
                name_elem = ET.SubElement(descr, "name")
                name_elem.text = item.get('name', '') if isinstance(item, dict) else str(item)
                ident_num = ET.SubElement(descr, "identNumber")
                ET.SubElement(ident_num, "manufacturerCode")
                qty = ET.SubElement(descr, "reqQuantity")
                qty.text = "По требованию"
        else:
            ET.SubElement(req_supplies, "noSupplies")

        # reqSpares
        req_spares = ET.SubElement(parent, "reqSpares")
        ET.SubElement(req_spares, "noSpares")

        # reqSafety
        safety_notes = data.get('safety_notes', [])
        safety_warnings = data.get('safety_warnings', [])
        safety_cautions = data.get('safety_cautions', [])
        req_safety = ET.SubElement(parent, "reqSafety")
        if safety_notes or safety_warnings or safety_cautions:
            safety_rqmts = ET.SubElement(req_safety, "safetyRqmts")
            for note_text in safety_notes:
                note = ET.SubElement(safety_rqmts, "note")
                note_para = ET.SubElement(note, "notePara")
                note_para.text = note_text
            for warn_text in safety_warnings:
                warning = ET.SubElement(safety_rqmts, "warning")
                wcp = ET.SubElement(warning, "warningAndCautionPara")
                wcp.text = warn_text
            for caut_text in safety_cautions:
                caution = ET.SubElement(safety_rqmts, "caution")
                wcp = ET.SubElement(caution, "warningAndCautionPara")
                wcp.text = caut_text
        else:
            ET.SubElement(req_safety, "noSafety")

    def _build_procedural_steps(self, parent: ET.Element, steps: List, counter: List = None):
        """Recursively build proceduralStep elements.

        Args:
            parent: Parent XML element (mainProcedure or proceduralStep)
            steps: List of step dicts with 'text' and optional 'substeps'
            counter: Mutable list with single int for sequential ID generation
        """
        if counter is None:
            counter = [1]

        for step in steps:
            step_id = f"stp-{counter[0]:05d}"
            counter[0] += 1
            proc_step = ET.SubElement(parent, "proceduralStep", id=step_id)

            text = step.get('text', '') if isinstance(step, dict) else str(step)
            para = ET.SubElement(proc_step, "para")
            para.text = text

            substeps = step.get('substeps', []) if isinstance(step, dict) else []
            if substeps:
                self._build_procedural_steps(proc_step, substeps, counter)

    def generate_procedure_module(self, dm_config: Dict, output_path: str,
                                   illustrations: Dict[str, str] = None,
                                   figure_info: List = None) -> str:
        """Generate complete S1000D procedure data module XML.

        Args:
            dm_config: Configuration dict with 'dm_code', 'title', 'content' (procedure_data)
            output_path: Directory to save XML file
            illustrations: Dict of illustration infoEntityIdent to file paths
            figure_info: List of figure info dicts

        Returns:
            Path to generated XML file
        """
        dmodule = self._create_base_xml_structure(schema_type="proced")

        # DOCTYPE
        doctype_lines = [
            '<!DOCTYPE dmodule [',
            '<!NOTATION jpg PUBLIC "+//ISBN 0-7923-9432-1::Graphic Notation//NOTATION Joint Photographic Experts Group Raster//EN">',
            '<!ENTITY PUBLICATION_LOGO SYSTEM "publication_logo.JPG" NDATA jpg>'
        ]
        entity_declarations = set()
        if illustrations:
            for info_entity_ident, file_path in illustrations.items():
                filename = os.path.basename(file_path)
                entity_declarations.add(f'<!ENTITY {info_entity_ident} SYSTEM "{filename}" NDATA jpg>')
        if figure_info:
            for fig in figure_info:
                file_path = fig['file']
                filename = os.path.basename(file_path)
                entity_name = filename.replace('.jpg', '')
                entity_declarations.add(f'<!ENTITY {entity_name} SYSTEM "{filename}" NDATA jpg>')
        doctype_lines.extend(sorted(entity_declarations))
        doctype_lines.append(']>')
        doctype = '\n'.join(doctype_lines)

        # identAndStatusSection (same as descriptive)
        ident_section = self._create_ident_and_status_section(
            dm_config['dm_code'], dm_config['title']
        )
        dmodule.append(ident_section)

        # content with <procedure>
        content_section = self._create_procedure_content_section(dm_config['content'])
        dmodule.append(content_section)

        # Generate filename
        dm_code_parts = dm_config['dm_code']
        filename = (
            f"DMC-{dm_code_parts['modelIdentCode']}-{dm_code_parts['systemDiffCode']}-"
            f"{dm_code_parts['systemCode']}-{dm_code_parts['subSystemCode']}"
            f"{dm_code_parts['subSubSystemCode']}-{dm_code_parts['assyCode']}-"
            f"{dm_code_parts['disassyCode']}{dm_code_parts['disassyCodeVariant']}-"
            f"{dm_code_parts['infoCode']}{dm_code_parts['infoCodeVariant']}-"
            f"{dm_code_parts['itemLocationCode']}_001_ru-RU.xml"
        )
        filepath = os.path.join(output_path, filename)

        # Format XML
        from xml.dom import minidom
        rough_string = ET.tostring(dmodule, encoding='unicode')
        reparsed = minidom.parseString(rough_string.encode('utf-8'))
        xml_content = reparsed.toprettyxml(indent='    ', newl='\n')
        xml_content = '\n'.join(xml_content.split('\n')[1:])
        xml_content = xml_content.strip()

        # Write
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n')
            f.write(doctype + '\n')
            f.write(xml_content)

        # Validate against proced.xsd
        is_valid, message = S1000DGenerator.validate_xml_against_schema(filepath, schema_file="xsd/proced.xsd")
        if is_valid:
            print(f"Validation PASSED for {filepath}")
        else:
            print(f"Validation FAILED for {filepath}: {message}")

        return filepath

    def generate_data_module(self, dm_config: Dict, output_path: str, illustrations: Dict[str, str] = None, figure_info: List = None) -> str:
        """
        Generate complete S1000D data module XML.

        Args:
            dm_config: Configuration dict with 'dm_code', 'title', 'content'
            output_path: Directory to save XML file
            illustrations: Dict of illustration infoEntityIdent to file paths

        Returns:
            Path to generated XML file
        """
        dmodule = self._create_base_xml_structure()

        # Add DOCTYPE with illustrations
        doctype_lines = [
            '<!DOCTYPE dmodule [',
            '<!NOTATION jpg PUBLIC "+//ISBN 0-7923-9432-1::Graphic Notation//NOTATION Joint Photographic Experts Group Raster//EN">',
            '<!ENTITY PUBLICATION_LOGO SYSTEM "publication_logo.JPG" NDATA jpg>'
        ]

        # Collect all entity declarations to avoid duplicates
        entity_declarations = set()

        # Add ENTITY declarations for all illustrations
        if illustrations:
            for info_entity_ident, file_path in illustrations.items():
                filename = os.path.basename(file_path)
                # Use full filename as entity name
                entity_declarations.add(f'<!ENTITY {info_entity_ident} SYSTEM "{filename}" NDATA jpg>')

        # Add ENTITY declarations for figure_info
        if figure_info:
            for fig in figure_info:
                file_path = fig['file']
                filename = os.path.basename(file_path)
                entity_name = filename.replace('.jpg', '')  # Remove extension for entity name
                entity_declarations.add(f'<!ENTITY {entity_name} SYSTEM "{filename}" NDATA jpg>')

        # Add unique entity declarations
        doctype_lines.extend(sorted(entity_declarations))

        doctype_lines.append(']>')
        doctype = '\n'.join(doctype_lines)

        # Add sections
        ident_section = self._create_ident_and_status_section(
            dm_config['dm_code'],
            dm_config['title']
        )
        dmodule.append(ident_section)

        content_section = self._create_content_section(dm_config['content'], figure_info)
        dmodule.append(content_section)

        # Generate filename
        dm_code_parts = dm_config['dm_code']
        filename = f"DMC-{dm_code_parts['modelIdentCode']}-{dm_code_parts['systemDiffCode']}-{dm_code_parts['systemCode']}-{dm_code_parts['subSystemCode']}{dm_code_parts['subSubSystemCode']}-{dm_code_parts['assyCode']}-{dm_code_parts['disassyCode']}{dm_code_parts['disassyCodeVariant']}-{dm_code_parts['infoCode']}{dm_code_parts['infoCodeVariant']}-{dm_code_parts['itemLocationCode']}_001_ru-RU.xml"

        filepath = os.path.join(output_path, filename)

        # Format XML for better readability
        from xml.dom import minidom
        rough_string = ET.tostring(dmodule, encoding='unicode')
        reparsed = minidom.parseString(rough_string.encode('utf-8'))
        xml_content = reparsed.toprettyxml(indent='    ', newl='\n')
        # Remove the XML declaration that minidom adds
        xml_content = '\n'.join(xml_content.split('\n')[1:])
        xml_content = xml_content.strip()

        # Write XML with proper encoding and formatting
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n')
            f.write(doctype + '\n')
            f.write(xml_content)

        # Validate generated XML against schema
        is_valid, message = S1000DGenerator.validate_xml_against_schema(filepath)
        if is_valid:
            print(f"Validation PASSED for {filepath}")
        else:
            print(f"Validation FAILED for {filepath}: {message}")

        return filepath

    @staticmethod
    def validate_xml_against_schema(xml_file: str, schema_file: str = "xsd/descript.xsd") -> Tuple[bool, str]:
        """
        Validate XML file against XSD schema.

        Args:
            xml_file: Path to XML file to validate
            schema_file: Path to XSD schema file

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Check if schema file exists
            if not os.path.exists(schema_file):
                return False, f"Schema file not found: {schema_file}"

            # Parse schema directly (no targetNamespace)
            with open(schema_file, 'r', encoding='utf-8') as f:
                schema_doc = ET.parse(f)

            schema = ET.XMLSchema(schema_doc)

            # Parse XML
            with open(xml_file, 'r', encoding='utf-8') as f:
                xml_doc = ET.parse(f)

            # Strip namespaces from XML to make it match schema without targetNamespace
            def strip_namespaces(element):
                ET.strip_elements(element, '{http://www.w3.org/2001/XMLSchema-instance}*', with_tail=False)
                ET.strip_attributes(element, '{http://www.w3.org/2001/XMLSchema-instance}*')
                ET.strip_attributes(element, '{http://www.s1000d.org/S1000D_4-1/xml_schema_flat/descript.xsd}*')
                ET.strip_attributes(element, '{http://www.s1000d.org/S1000D_4-1/xml_schema_flat/proced.xsd}*')
                for child in element:
                    strip_namespaces(child)
                element.tag = element.tag.split('}', 1)[-1] if '}' in element.tag else element.tag

            strip_namespaces(xml_doc.getroot())

            # Now validate the namespace-free XML against namespace-free schema
            is_valid = schema.validate(xml_doc)

            if is_valid:
                return True, "XML is valid according to schema"
            else:
                # Collect validation errors
                errors = []
                for error in schema.error_log:
                    errors.append(f"Line {error.line}, Column {error.column}: {error.message}")
                error_msg = "XML validation failed:\n" + "\n".join(errors)
                return False, error_msg

        except Exception as e:
            return False, f"Validation error: {str(e)}"


    @staticmethod
    def validate_generated_modules(output_dir: str) -> Dict[str, Tuple[bool, str]]:
        """
        Validate all XML files in output directory against schema.

        Args:
            output_dir: Directory containing XML files

        Returns:
            Dict mapping filenames to (is_valid, error_message) tuples
        """
        validation_results = {}

        # Find all XML files
        xml_files = [f for f in os.listdir(output_dir) if f.endswith('.xml')]

        for xml_file in xml_files:
            filepath = os.path.join(output_dir, xml_file)
            is_valid, message = S1000DGenerator.validate_xml_against_schema(filepath)
            validation_results[xml_file] = (is_valid, message)
            print(f"Validation for {xml_file}: {'PASS' if is_valid else 'FAIL'}")

            if not is_valid:
                print(f"  Errors: {message[:200]}..." if len(message) > 200 else f"  Errors: {message}")

        return validation_results


def create_data_module_config(title_ru: str, info_name_ru: str, dm_code: Dict, content: Dict, enterprise_name: str = "Организация не задана", originator_name: str = "Организация не задана") -> Dict:
    """
    Helper to create DM config dict.

    Args:
        title_ru: Russian title
        info_name_ru: Russian info name
        dm_code: DM code components
        content: Content dict
        enterprise_name: Name for responsible company
        originator_name: Name for originator company

    Returns:
        Config dict for generator
    """
    return {
        'dm_code': dm_code,
        'title': {
            'techName': title_ru,
            'infoName': info_name_ru,
            'enterpriseName': enterprise_name,
            'originatorName': originator_name
        },
        'content': content
    }
