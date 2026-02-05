#!/usr/bin/env python3
"""
Test script to analyze the multi-level list issue described by the user.
The issue: nested unnumbered lists with different bullet types (– and •) 
where the inner list is incorrectly identified as a numbered paragraph header.
"""

from parsers.elements_analyzer import analyze_document_elements
from docx import Document
import re

def test_multilevel_list_issue():
    """Test the specific multi-level list issue."""
    
    # Create a test document with the problematic structure
    # For now, let's analyze the existing document to find similar patterns
    doc = Document('docs/РСУ_адаптированная.docx')
    
    print("Searching for multi-level list patterns...")
    print("=" * 60)
    
    # Look for paragraphs with "–" markers that might contain nested lists with "•"
    dash_paragraphs = []
    bullet_paragraphs = []
    
    for i, paragraph in enumerate(doc.paragraphs):
        text = paragraph.text.strip()
        if text.startswith('–') or text.startswith('-'):
            dash_paragraphs.append((i, text))
        elif text.startswith('•'):
            bullet_paragraphs.append((i, text))
    
    print(f"Found {len(dash_paragraphs)} paragraphs starting with dash (–)")
    print(f"Found {len(bullet_paragraphs)} paragraphs starting with bullet (•)")
    
    # Look for patterns where bullet paragraphs follow dash paragraphs
    print("\nLooking for potential multi-level list structures...")
    print("-" * 60)
    
    for dash_idx, dash_text in dash_paragraphs:
        # Check if next few paragraphs are bullet items
        for bullet_idx, bullet_text in bullet_paragraphs:
            if bullet_idx == dash_idx + 1:  # Immediately following
                print(f"Potential multi-level list found:")
                print(f"  Paragraph {dash_idx}: {dash_text[:80]}...")
                print(f"  Paragraph {bullet_idx}: {bullet_text[:80]}...")
                
                # Check current analysis
                elements = analyze_document_elements(doc)
                
                # Find these paragraphs in the elements
                dash_elem = None
                bullet_elem = None
                
                for elem in elements:
                    if elem.get('start_para') == dash_idx:
                        dash_elem = elem
                    if elem.get('start_para') == bullet_idx:
                        bullet_elem = elem
                
                if dash_elem:
                    print(f"    Dash paragraph detected as: {dash_elem['type']}")
                if bullet_elem:
                    print(f"    Bullet paragraph detected as: {bullet_elem['type']}")
                    if bullet_elem['type'] == 'numbered_paragraph_header':
                        print("    *** ISSUE: Bullet incorrectly identified as numbered header! ***")
                
                print()
    
    # Also test with a synthetic example
    print("Testing with synthetic multi-level list example...")
    print("-" * 60)
    
    # For now, let's just print the problematic pattern from the user's description
    example_text = """–	в положении ВОЗДУХ - выключатели АСП "В-П" устанавливаются на мгновенное срабатывание;
–	в положении ЗЕМЛЯ:
•	выключатели АСП "В-П" устанавливаются на замедление;
•	выключатели АСП "В-В" устанавливаются на контактное срабатывание."""
    
    print("Example pattern from user:")
    print(example_text)
    print()
    
    # Analyze what the current logic would do
    lines = example_text.split('\n')
    for i, line in enumerate(lines):
        if line.strip():
            # Simulate the list detection logic
            if line.strip().startswith('–'):
                print(f"Line {i+1} ('{line[:30]}...'): Would be detected as unnumbered_list ✓")
            elif line.strip().startswith('•'):
                print(f"Line {i+1} ('{line[:30]}...'): Would be detected as unnumbered_list ✓")
                # But check if it might also be detected as numbered header
                text = line.strip()
                if (len(text.strip()) < 200 and 
                    not text.endswith(('.', '!', '?')) and
                    not any(word in text.lower() for word in ['представляет', 'обеспечивает', 'осуществляет', 'является', 'который', 'которая', 'которое', 'которые'])):
                    print(f"  WARNING: Also meets numbered header criteria!")

if __name__ == "__main__":
    test_multilevel_list_issue()
