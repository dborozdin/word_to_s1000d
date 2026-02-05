"""
LLM integration package for document structure classification.
Provides optional LLM-assisted element classification using Ollama.
"""

from .structure_classifier import DocumentStructureClassifier
from .ollama_client import OllamaClient

__all__ = ['DocumentStructureClassifier', 'OllamaClient']
