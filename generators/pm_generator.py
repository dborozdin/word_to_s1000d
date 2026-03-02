"""
Publication Module generator.
Creates S1000D publication module XML files that reference data modules.
"""

import os
from datetime import datetime
from typing import Dict, List, Optional
from lxml import etree as ET


class PMGenerator:
    """Generator for S1000D publication modules."""

    def __init__(self, model_ident: str = "S5"):
        """
        Initialize generator with base parameters.

        Args:
            model_ident: Model identifier code
        """
        self.model_ident = model_ident

    def _create_base_pm_structure(self) -> ET.Element:
        """Create basic pm element with namespaces."""
        # Create XML string with proper namespaces
        xml_str = '''<pm xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                      xsi:noNamespaceSchemaLocation="http://www.s1000d.org/S1000D_4-1/xml_schema_flat/pm.xsd"
                      xmlns:xlink="http://www.w3.org/1999/xlink">
        </pm>'''

        # Parse into element tree
        pm = ET.fromstring(xml_str)

        return pm

    def _create_ident_and_status_section(self, pm_config: Dict, date: datetime) -> ET.Element:
        """Create identAndStatusSection for PM."""
        section = ET.Element("identAndStatusSection")

        # pmAddress
        pm_address = ET.SubElement(section, "pmAddress")
        pm_ident = ET.SubElement(pm_address, "pmIdent")

        # pmCode
        pm_code_data = pm_config.get('pmCode', {})
        pm_code = ET.SubElement(pm_ident, "pmCode",
                               modelIdentCode=pm_code_data.get('modelIdentCode', self.model_ident),
                               pmIssuer=pm_code_data.get('pmIssuer', 'SFX44'),
                               pmNumber=pm_code_data.get('pmNumber', 'ETP05'),
                               pmVolume=pm_code_data.get('pmVolume', '00'))

        # Language and issue
        lang_elem = ET.SubElement(pm_ident, "language", languageIsoCode="ru", countryIsoCode="RU")
        issue_elem = ET.SubElement(pm_ident, "issueInfo", issueNumber="001", inWork="00")

        # Address items
        pm_address_items = ET.SubElement(pm_address, "pmAddressItems")
        issue_date = ET.SubElement(pm_address_items, "issueDate",
                                  year=str(date.year),
                                  month=str(date.month).zfill(2),
                                  day=str(date.day).zfill(2))

        # pmTitle
        pm_title = ET.SubElement(pm_address_items, "pmTitle")
        pm_title.text = pm_config.get('pmTitle', 'Publication Module')

        # pmStatus
        pm_status = ET.SubElement(section, "pmStatus")

        security = ET.SubElement(pm_status, "security", securityClassification="01")

        logo = ET.SubElement(pm_status, "logo")
        symbol = ET.SubElement(logo, "symbol", infoEntityIdent="PUBLICATION_LOGO")

        responsible_company = ET.SubElement(pm_status, "responsiblePartnerCompany", enterpriseCode="00000")
        enterprise_name = ET.SubElement(responsible_company, "enterpriseName")
        enterprise_name.text = pm_config.get('enterpriseName', "Организация не задана")

        originator = ET.SubElement(pm_status, "originator", enterpriseCode="00000")
        originator_name = ET.SubElement(originator, "enterpriseName")
        originator_name.text = pm_config.get('originatorName', "Организация не задана")

        applic = ET.SubElement(pm_status, "applic")
        display_text = ET.SubElement(applic, "displayText")
        simple_para = ET.SubElement(display_text, "simplePara")
        simple_para.text = "Все"

        # BREX reference
        brex_dm_ref = ET.SubElement(pm_status, "brexDmRef")
        dm_ref = ET.SubElement(brex_dm_ref, "dmRef")
        dm_ref_ident = ET.SubElement(dm_ref, "dmRefIdent")
        brex_dm_code = ET.SubElement(dm_ref_ident, "dmCode",
                                    modelIdentCode=self.model_ident,
                                    systemDiffCode="A",
                                    systemCode="00",
                                    subSystemCode="0",
                                    subSubSystemCode="0",
                                    assyCode="00",
                                    disassyCode="00",
                                    disassyCodeVariant="A",
                                    infoCode="022",
                                    infoCodeVariant="A",
                                    itemLocationCode="D")

        quality_assurance = ET.SubElement(pm_status, "qualityAssurance")
        unverified = ET.SubElement(quality_assurance, "unverified")

        return section

    def _create_content_section(self, dm_refs: List[Dict], pm_title: str = "Руководство") -> ET.Element:
        """Create content section with dmRefs organized in pmEntries."""
        content = ET.Element("content")

        # Single root pmEntry — all dmRefs go directly here
        main_pm_entry = ET.SubElement(content, "pmEntry")
        main_pm_entry_title = ET.SubElement(main_pm_entry, "pmEntryTitle")
        main_pm_entry_title.text = pm_title

        for ref in dm_refs:
            self._add_dm_ref(main_pm_entry, ref)

        # Add BREX and ACIR refs
        self._add_brex_ref(main_pm_entry)
        self._add_acir_ref(main_pm_entry)

        return content

    def _categorize_dm_refs(self, dm_refs: List[Dict]) -> Dict[str, List[Dict]]:
        """Categorize DM references for organized pmEntry structure."""
        categories = {}

        for ref in dm_refs:
            dm_code = ref['dm_code']
            system_code = dm_code.get('systemCode', '00')

            # Categorize based on infoCode or systemCode
            info_code = dm_code.get('infoCode', '000')

            if info_code == '071':
                category = "Нормы расхода запасных частей и материалов"
            elif info_code == '075':
                category = "Нормы расхода материалов"
            elif system_code == '05' and info_code == '00D':
                category = "Ресурсы и сроки службы"
            elif system_code == '05' and info_code == '000' and dm_code.get('subSystemCode') == '2':
                category = "Перечни работ ТО"
            elif system_code == '05' and info_code == '000' and dm_code.get('subSystemCode') == '4':
                category = "Проверки в объеме планового ТО"
            else:
                category = "general"  # General or first DM

            if category not in categories:
                categories[category] = []
            categories[category].append(ref)

        return categories

    def _add_dm_ref(self, parent_element: ET.Element, dm_ref_data: Dict):
        """Add a dmRef element to parent."""
        dm_ref = ET.SubElement(parent_element, "dmRef")

        # dmRefIdent
        dm_ref_ident = ET.SubElement(dm_ref, "dmRefIdent")

        dm_code_data = dm_ref_data['dm_code']
        dm_code = ET.SubElement(dm_ref_ident, "dmCode",
                               modelIdentCode=dm_code_data.get('modelIdentCode', self.model_ident),
                               systemDiffCode=dm_code_data.get('systemDiffCode', 'A'),
                               systemCode=dm_code_data.get('systemCode', '00'),
                               subSystemCode=dm_code_data.get('subSystemCode', '0'),
                               subSubSystemCode=dm_code_data.get('subSubSystemCode', '0'),
                               assyCode=dm_code_data.get('assyCode', '00'),
                               disassyCode=dm_code_data.get('disassyCode', '00'),
                               disassyCodeVariant=dm_code_data.get('disassyCodeVariant', 'A'),
                               infoCode=dm_code_data.get('infoCode', '000'),
                               infoCodeVariant=dm_code_data.get('infoCodeVariant', 'A'),
                               itemLocationCode=dm_code_data.get('itemLocationCode', 'A'))

        issue_elem = ET.SubElement(dm_ref_ident, "issueInfo", issueNumber="001", inWork="00")
        lang_elem = ET.SubElement(dm_ref_ident, "language", languageIsoCode="ru", countryIsoCode="RU")

        # dmRefAddressItems
        dm_ref_address_items = ET.SubElement(dm_ref, "dmRefAddressItems")
        dm_title = ET.SubElement(dm_ref_address_items, "dmTitle")

        tech_name = ET.SubElement(dm_title, "techName")
        tech_name.text = dm_ref_data.get('techName', '')

        info_name = ET.SubElement(dm_title, "infoName")
        info_name.text = dm_ref_data.get('infoName', '')

    def _add_brex_ref(self, parent_element: ET.Element):
        """Add BREX DM reference."""
        dm_ref = ET.SubElement(parent_element, "dmRef", id="tgbExt-0000")

        dm_ref_ident = ET.SubElement(dm_ref, "dmRefIdent")
        dm_code = ET.SubElement(dm_ref_ident, "dmCode",
                               modelIdentCode=self.model_ident,
                               systemDiffCode="A",
                               systemCode="00",
                               subSystemCode="0",
                               subSubSystemCode="0",
                               assyCode="00",
                               disassyCode="00",
                               disassyCodeVariant="A",
                               infoCode="022",
                               infoCodeVariant="A",
                               itemLocationCode="D")

        issue_elem = ET.SubElement(dm_ref_ident, "issueInfo", issueNumber="001", inWork="00")
        lang_elem = ET.SubElement(dm_ref_ident, "language", languageIsoCode="ru", countryIsoCode="RU")

        dm_ref_address_items = ET.SubElement(dm_ref, "dmRefAddressItems")
        dm_title = ET.SubElement(dm_ref_address_items, "dmTitle")

        tech_name = ET.SubElement(dm_title, "techName")  # Empty as in example
        info_name = ET.SubElement(dm_title, "infoName")
        info_name.text = "Business rules exchange data module"

    def _add_acir_ref(self, parent_element: ET.Element):
        """Add Applicability Common Information Repository reference."""
        dm_ref = ET.SubElement(parent_element, "dmRef", id="tgbExt-0001")

        dm_ref_ident = ET.SubElement(dm_ref, "dmRefIdent")
        dm_code = ET.SubElement(dm_ref_ident, "dmCode",
                               modelIdentCode=self.model_ident,
                               systemDiffCode="A",
                               systemCode="00",
                               subSystemCode="0",
                               subSubSystemCode="0",
                               assyCode="00",
                               disassyCode="00",
                               disassyCodeVariant="A",
                               infoCode="0A2",
                               infoCodeVariant="A",
                               itemLocationCode="D")

        issue_elem = ET.SubElement(dm_ref_ident, "issueInfo", issueNumber="001", inWork="00")
        lang_elem = ET.SubElement(dm_ref_ident, "language", languageIsoCode="ru", countryIsoCode="RU")

        dm_ref_address_items = ET.SubElement(dm_ref, "dmRefAddressItems")
        dm_title = ET.SubElement(dm_ref_address_items, "dmTitle")

        tech_name = ET.SubElement(dm_title, "techName")  # Empty as in example
        info_name = ET.SubElement(dm_title, "infoName")
        info_name.text = "Applicability common information repository"

    def generate_publication_module(self, pm_config: Dict, dm_refs: List[Dict], output_path: str, illustrations: Dict[str, str] = None) -> str:
        """
        Generate complete S1000D publication module XML.

        Args:
            pm_config: Configuration dict with 'modelIdentCode', 'pmIssuer', etc.
            dm_refs: List of DM reference data (dict with 'dm_code', 'techName', 'infoName')
            output_path: Directory to save XML file

        Returns:
            Path to generated XML file
        """
        pm = self._create_base_pm_structure()

        # Add DOCTYPE with illustrations
        doctype_lines = [
            '<!DOCTYPE pm [',
            '<!NOTATION jpg PUBLIC "+//ISBN 0-7923-9432-1::Graphic Notation//NOTATION Joint Photographic Experts Group Raster//EN">',
            '<!ENTITY PUBLICATION_LOGO SYSTEM "publication_logo.JPG" NDATA jpg>'
        ]

        # Add ENTITY declarations for all illustrations
        if illustrations:
            for info_entity_ident, file_path in illustrations.items():
                filename = os.path.basename(file_path)
                # Use full filename as entity name
                doctype_lines.append(f'<!ENTITY {info_entity_ident} SYSTEM "{filename}" NDATA jpg>')

        doctype_lines.append(']>')
        doctype = '\n'.join(doctype_lines)

        # Generate filename early so it can be used as pmEntryTitle
        pm_code = pm_config.get('pmCode', {})
        filename = f"PMC-{pm_code.get('modelIdentCode', self.model_ident)}-{pm_code.get('pmIssuer', 'SFX44')}-{pm_code.get('pmNumber', 'ETP05')}-{pm_code.get('pmVolume', '00')}_001-ru-RU.xml"
        pm_entry_title = filename.replace('.xml', '')

        # Current date
        current_date = datetime.now()

        # Add sections
        ident_section = self._create_ident_and_status_section(pm_config, current_date)
        pm.append(ident_section)

        content_section = self._create_content_section(dm_refs, pm_entry_title)
        pm.append(content_section)

        filepath = os.path.join(output_path, filename)

        # Format XML for better readability
        from xml.dom import minidom
        rough_string = ET.tostring(pm, encoding='unicode')
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
        is_valid, message = PMGenerator.validate_xml_against_schema(filepath)
        if is_valid:
            print(f"Validation PASSED for {filepath}")
        else:
            print(f"Validation FAILED for {filepath}: {message}")

        return filepath

    @staticmethod
    def validate_xml_against_schema(xml_file: str, schema_file: str = None) -> tuple[bool, str]:
        """
        Validate XML file against XSD schema.

        Args:
            xml_file: Path to XML file to validate
            schema_file: Path to XSD schema file

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            if schema_file is None:
                from app_paths import get_xsd_path
                schema_file = get_xsd_path('pm.xsd')
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
                ET.strip_attributes(element, '{http://www.s1000d.org/S1000D_5-0/xml_schema_flat/pm.xsd}*')
                ET.strip_attributes(element, '{http://www.w3.org/1999/xlink}*')
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


def create_pm_config(model_ident_code: str, pm_issuer: str = "SFX44", pm_number: str = "ETP05", pm_volume: str = "00", pm_title: str = "Руководство по техническому обслуживанию", enterprise_name: str = "Организация не задана", originator_name: str = "Организация не задана") -> Dict:
    """
    Helper to create PM config dict.

    Args:
        model_ident_code: Model identifier code
        pm_issuer: PM issuer code
        pm_number: PM number
        pm_volume: PM volume
        pm_title: Publication module title
        enterprise_name: Name for responsible company
        originator_name: Name for originator company

    Returns:
        Config dict for PM generator
    """
    return {
        'pmCode': {
            'modelIdentCode': model_ident_code,
            'pmIssuer': pm_issuer,
            'pmNumber': pm_number,
            'pmVolume': pm_volume
        },
        'pmTitle': pm_title,
        'enterpriseName': enterprise_name,
        'originatorName': originator_name
    }


def create_dm_ref_data(dm_code: Dict, tech_name: str, info_name: str) -> Dict:
    """
    Helper to create DM reference data dict.

    Args:
        dm_code: DM code dictionary
        tech_name: Technical name
        info_name: Information name

    Returns:
        DM reference dict
    """
    return {
        'dm_code': dm_code,
        'techName': tech_name,
        'infoName': info_name
    }
