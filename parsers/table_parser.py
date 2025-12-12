"""
Table parser for docx documents.
Extracts table data for conversion to S1000D format.
"""

from typing import Dict, List
from docx import Document


def extract_tables(doc: Document) -> List[Dict[str, List[List[str]]]]:
    """
    Extract all tables from document with metadata.

    Args:
        doc: Docx document object

    Returns:
        List of tables, each as dict with 'rows' key containing list of lists
    """
    tables_data = []

    for table in doc.tables:
        table_data = {'rows': []}

        # Extract rows
        for row in table.rows:
            row_data = []
            for cell in row.cells:
                cell_text = cell.text.strip()
                row_data.append(cell_text)
            table_data['rows'].append(row_data)

        tables_data.append(table_data)

    return tables_data


def get_tables_by_reference(doc: Document, table_references: Dict[int, str] = None) -> Dict[str, Dict[str, List[List[str]]]]:
    """
    Extract tables mapped to their reference names.

    Args:
        doc: Docx document object
        table_references: Optional mapping of table index to reference name

    Returns:
        Dictionary of table reference -> table data
    """
    if table_references is None:
        # Use "Table 1", "Table 2", etc.
        table_references = {i: f"Table {i+1}" for i in range(len(doc.tables))}

    tables_dict = {}

    for idx, table in enumerate(doc.tables):
        ref_name = table_references.get(idx, f"Table {idx+1}")

        table_data = {'rows': []}
        for row in table.rows:
            row_data = []
            for cell in row.cells:
                row_data.append(cell.text.strip())
            table_data['rows'].append(row_data)

        tables_dict[ref_name] = table_data

    return tables_dict


def convert_table_to_s1000d_format(table_data: Dict[str, List[List[str]]]) -> str:
    """
    Convert table data to basic S1000D table XML structure.

    Args:
        table_data: Table data as rows of lists

    Returns:
        Basic XML string representation of table
    """
    if not table_data.get('rows'):
        return ""

    rows = table_data['rows']
    num_cols = max(len(row) for row in rows) if rows else 0

    # Build basic table entry
    table_entries = []

    for row in rows:
        row_entries = []
        for col_idx, cell in enumerate(row):
            if cell.strip():
                row_entries.append(f"<entry><para>{cell}</para></entry>")
            else:
                row_entries.append("<entry></entry>")
        # Pad missing columns if needed
        while len(row_entries) < num_cols:
            row_entries.append("<entry></entry>")

        table_entries.append(f"<row>{''.join(row_entries)}</row>")

    return f"<table><tgroup cols=\"{num_cols}\"><tbody>{''.join(table_entries)}</tbody></tgroup></table>"
