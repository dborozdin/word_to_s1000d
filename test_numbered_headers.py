#!/usr/bin/env python3
"""
Test script to check numbered paragraph headers detection
"""

from docx import Document
from parsers.elements_analyzer import analyze_document_elements

def test_numbered_headers():
    doc = Document('docs/РСУ_адаптированная.docx')
    elements = analyze_document_elements(doc)

    # Count and show numbered paragraph headers
    numbered_headers = [elem for elem in elements if elem['type'] == 'numbered_paragraph_header']
    print(f'Found {len(numbered_headers)} numbered paragraph headers:')

    for i, header in enumerate(numbered_headers, 1):
        print(f'{i}. "{header["content"]}"')
        print(f'   Details: {header["details"]}')
        print(f'   XML: {header["xml_example"]}')
        print()

if __name__ == "__main__":
    test_numbered_headers()
