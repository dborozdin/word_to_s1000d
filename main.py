"""
Main entry point for Word to S1000D conversion.
Determines module type and delegates to appropriate processing script.
"""

from typing import Dict, Optional
import sys
import os
import configparser


def determine_module_type(doc_path: str) -> str:
    """
    Determine the type of data module to create from the document.

    This is a stub function that will be expanded for different module types:
    - Descriptive modules (current implementation)
    - Task modules (technological maps)
    - Fault isolation modules
    - Maintenance procedures

    Args:
        doc_path: Path to the source document

    Returns:
        Module type identifier
    """
    # For now, assume all documents are descriptive modules
    # Later, this could analyze document content/structure to determine type
    return "descriptive"


def route_to_processor(module_type: str, doc_path: str, output_dir: str):
    """
    Route to appropriate processing script based on module type.

    Args:
        module_type: Type of module to create
        doc_path: Path to source document
        output_dir: Output directory for generated files
    """
    if module_type == "descriptive":
        # Import and run descriptive module processor
        from processing_scripts import descriptive_processor
        descriptive_processor.process_descriptive_document(doc_path, output_dir)
    elif module_type == "task":
        # Future: task module processor for technological maps
        print("Task module processing not implemented yet")
    elif module_type == "fault_isolation":
        # Future: fault isolation module processor
        print("Fault isolation module processing not implemented yet")
    elif module_type == "maintenance":
        # Future: maintenance procedure module processor
        print("Maintenance module processing not implemented yet")
    else:
        print(f"Unknown module type: {module_type}")


def main():
    """Main entry point."""
    # Read configuration
    config = configparser.ConfigParser()
    config.read('config.ini', encoding='utf-8')
    output_dir = config.get('processing', 'output_dir', fallback='./tg_web/publications')
    input_dir = config.get('processing', 'input_dir', fallback='./docs')

    if len(sys.argv) == 2:
        doc_path = sys.argv[1]
    elif len(sys.argv) == 1:
        docx_file = config.get('processing', 'docx_file')
        doc_path = os.path.join(input_dir, docx_file)
    else:
        print("Usage: python main.py [<docx_file>]")
        print("If no argument provided, docx_file will be read from config.ini")
        sys.exit(1)

    if not os.path.exists(doc_path):
        print(f"Error: Document file not found: {doc_path}")
        sys.exit(1)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    else:
        # Clear output directory before generation
        for file_name in os.listdir(output_dir):
            file_path = os.path.join(output_dir, file_name)
            if os.path.isfile(file_path):
                os.unlink(file_path)

    # Determine module type
    module_type = determine_module_type(doc_path)
    print(f"Detected module type: {module_type}")

    # Route to appropriate processor
    route_to_processor(module_type, doc_path, output_dir)


if __name__ == "__main__":
    main()
