# Word to S1000D Conversion Tool

This Python project converts Microsoft Word (.docx) documents into ASD S1000D data modules in XML format. The tool is designed for aerospace technical documentation, specifically for converting descriptive module content.

## Project Structure

```
word_to_s1000d/
├── main.py                         # Main entry point with module type detection
├── parsers/                        # Document parsing modules
│   ├── text_parser.py             # Heading-based text extraction
│   ├── table_parser.py            # Table conversion utilities
│   ├── list_parser.py             # List element extraction
│   └── illustration_parser.py     # Image extraction and management
├── generators/                     # XML generation components
│   └── s1000d_generator.py         # S1000D DM XML structure creation
├── processing_scripts/             # Document type processing
│   └── descriptive_processor.py    # Descriptive module orchestration
├── output/                         # Generated XML modules and extracted images
├── manual_data_modules/            # Reference S1000D modules
└── docs/                          # Source Word documents
```

## Core Components

### 1. Main Entry Point (main.py)

**Purpose**: Orchestrates the conversion process and provides extensibility for different module types.

```python
def determine_module_type(doc_path: str) -> str:
    # TODO: Future implementation for different document types
    # Currently returns "descriptive" for all documents
    # Will analyze document structure to determine:
    # - "descriptive": System/component descriptions (current scope)
    # - "task": Technological maps, maintenance procedures
    # - "fault_isolation": Troubleshooting guides
    # - "maintenance": Scheduled maintenance tasks
    return "descriptive"

def route_to_processor(module_type: str, doc_path: str, output_dir: str):
    # Routes to appropriate processing script based on detected type
    # Descriptive modules handled by descriptive_processor.py
    # Future expansion will add more processors
```

### 2. Document Parsing Modules

#### text_parser.py - Text Extraction
```python
def extract_text_by_headings(doc: Document) -> Dict[str, str]:
    """
    Groups document content by heading hierarchy.
    Returns: {'Section Title': 'Section content...'}
    Uses Heading 1, Heading 2 styles to identify document structure.
    """

def get_document_structure(doc: Document) -> List[str]:
    """
    Extracts all heading titles in order.
    Used for section categorization and DMC mapping.
    """
```

#### table_parser.py - Table Processing
```python
def extract_tables(doc: Document) -> List[Dict[str, List[List[str]]]]:
    """
    Converts Word tables to structured data.
    Returns: [{'rows': [['cell1', 'cell2'], ['cell3', 'cell4']]}]
    """

def convert_table_to_s1000d_format(table_data: Dict) -> str:
    """
    Transforms table data into S1000D XML structure:
    <table><tgroup cols="N"><tbody><row><entry>data</entry></row></tbody></tgroup></table>
    """
```

#### list_parser.py - List Extraction
```python
def extract_lists(doc: Document) -> List[Dict[str, str]]:
    """
    Identifies and extracts bulleted/numbered lists.
    Returns: [{'type': 'bullet', 'items': ['item1', 'item2']}]
    Uses heuristic detection based on bullet markers and indentation.
    """

def convert_list_to_s1000d_randomlist(list_data: Dict) -> str:
    """
    Converts to S1000D randomList format:
    <randomList listItemPrefix="pf02"><listItem><para>text</para></listItem></randomList>
    """
```

#### illustration_parser.py - Media Handling
```python
def extract_illustrations(doc: Document, output_dir: str = "output") -> Dict[str, str]:
    """
    Extracts embedded images from Word document with S1000D naming convention.
    Creates output/graphics/ subdirectory and saves files as:
    GS5-A-120-10-00-00A-041A-A_001_RU-RU-GRAPHIC{N}.jpg
    Returns mapping of reference names to file paths.
    """

def find_image_references(text: str) -> List[Tuple[str, str]]:
    """
    Scans text for figure references: "рисунок 1", "figure 1", etc.
    Maps to S1000D GRAPHIC naming with 0-based indexing.
    """
```

### 3. XML Generation (s1000d_generator.py)

```python
class S1000DGenerator:
    """
    Creates complete S1000D dmodule XML files.
    Includes proper namespace declarations, DOCTYPE, and structure validation.
    """

    def generate_data_module(self, dm_config: Dict, output_path: str) -> str:
        """
        Main generation method creating:
        - identAndStatusSection with DM address and metadata
        - content section with description, paragraphs, tables, lists
        - Proper XML formatting with DOCTYPE declaration
        - Filename: DMC-model-subSys-etc-infoCode-issue_lang.xml
        """
```

### 4. Descriptive Processor (processing_scripts/descriptive_processor.py)

**Orchestrates the complete conversion process:**

```python
def map_heading_to_info_code(heading: str, component_index: int = 0) -> Dict:
    """
    Maps Russian document headings to S1000D infoCodes:

    System Level Modules:
    - "Общие сведения" → infoCode=011A (Purpose/Purpose)
    - "Состав РСУО" → infoCode=012A (Description)
    - "Информационный обмен" → infoCode=014A (Interface info)
    - Operation modes → infoCode=015A/B/C/D (different variants)

    Component Level Modules:
    - Each equipment/unit → infoCode=017A with subSubSystemCode=01,02,...
    - Base DMC: DMC-S5-A-120-10-XX-00-00A-017A-A
    """

def group_sections_by_type(headings: List[str]) -> Dict[str, List[int]]:
    """
    Categorizes document sections for module creation:
    - system_purpose: General system purpose sections
    - system_description: Composition and equipment description
    - system_operation: Operation modes and procedures
    - components: Individual equipment/unit descriptions
    """

def process_descriptive_document(doc_path: str, output_dir: str):
    """
    Main processing workflow:
    1. Parse document content using all parser modules
    2. Group sections by type
    3. Create appropriate S1000D data modules for each group
    4. Generate XML files with proper DMC codes
    5. Extract and organize illustrations
    """
```

## Conversion Workflow

1. **Document Analysis**: Identify heading structure and content types
2. **Content Parsing**: Extract text, tables, lists, and illustrations
3. **Section Classification**: Group content into logical S1000D modules
4. **Code Mapping**: Assign appropriate DMC codes based on content type
5. **XML Generation**: Create well-formed S1000D dmodule XML files
6. **Media Organization**: Extract and reference illustrations

## Usage

```bash
# Convert a Word document to S1000D modules
python main.py "docs/source_document.docx" "output_directory"
```

## Building the Distribution

To build the standalone PyInstaller distribution (incl. the bundled `tg_web`
viewer), see [BUILD.md](BUILD.md). Note: binaries are stored in Git LFS — run
`git lfs install && git lfs pull` after cloning.

## Generated Output

- **XML Data Modules**: Properly formatted S1000D 4.1 XML files
- **Illustrations**: Extracted images saved as JPG files
- **Module Organization**: Multiple DMs created from single source document

## Extensibility

The framework is designed for expansion to other S1000D module types:
- **Task Modules**: Technological maps, maintenance procedures
- **Fault Isolation Modules**: Troubleshooting and diagnostics
- **Maintenance Modules**: Scheduled maintenance tasks

The `determine_module_type()` and `route_to_processor()` functions in `main.py` provide the architecture for adding new module types.

## Dependencies

- `python-docx`: Word document parsing
- `lxml`: XML generation and manipulation
- `Pillow`: Image processing and saving

## Validation

Generated XML conforms to S1000D 4.1 specifications with:
- Proper DOCTYPE declarations
- Correct namespace handling
- Valid dmodule structure
- Appropriate metadata and content elements

## Results

Successfully processes complex aerospace technical documentation, generating multiple properly coded S1000D data modules from structured Word documents.
