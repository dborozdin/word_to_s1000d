"""
Document structure classifier using LLM with caching and fallback to heuristics.
"""

import hashlib
import json
import os
from typing import Dict, Any, Optional
from dataclasses import dataclass

from .ollama_client import OllamaClient


@dataclass
class ElementClassification:
    """Result of element classification."""
    element_type: str  # 'header', 'list_item', 'paragraph', 'table_intro'
    confidence: float  # 0.0 to 1.0
    reasoning: str
    source: str  # 'llm', 'heuristic', 'cache'
    list_level: Optional[int] = None


class DocumentStructureClassifier:
    """
    LLM-powered document structure classifier with caching.

    Falls back to heuristics when LLM is unavailable or confidence is low.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize classifier with configuration.

        Args:
            config: Dict with keys:
                - enabled: bool - whether to use LLM
                - ollama_url: str - Ollama API URL
                - ollama_model: str - Model name
                - confidence_threshold: float - Below this, fall back to heuristics
                - cache_enabled: bool - Whether to cache LLM responses
                - cache_dir: str - Directory for cache files
        """
        self.config = config
        self.llm_enabled = config.get('enabled', False)
        self.confidence_threshold = config.get('confidence_threshold', 0.7)
        self.cache_enabled = config.get('cache_enabled', True)
        self.cache_dir = config.get('cache_dir', '.llm_cache')

        self._client = None
        self._cache = {}  # In-memory cache

        # Load disk cache if enabled
        if self.cache_enabled and os.path.exists(self._cache_file_path):
            self._load_cache()

    @property
    def _cache_file_path(self) -> str:
        """Path to the cache file."""
        return os.path.join(self.cache_dir, 'classification_cache.json')

    def _get_client(self) -> OllamaClient:
        """Get or create Ollama client."""
        if self._client is None:
            self._client = OllamaClient(
                url=self.config.get('ollama_url', 'http://localhost:11434'),
                model=self.config.get('ollama_model', 'gemma3:4b-it-qat')
            )
        return self._client

    def _make_cache_key(self, text: str, context: Dict[str, Any]) -> str:
        """
        Create cache key from text and context.

        Args:
            text: Element text
            context: Classification context

        Returns:
            Hash string for cache lookup
        """
        # Include relevant context in cache key
        key_data = {
            'text': text,
            'prev_type': context.get('prev_element', {}).get('type', ''),
            'prev_ending': context.get('prev_text_ending', ''),
            'style': context.get('style_name', '')
        }
        key_str = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(key_str.encode('utf-8')).hexdigest()

    def _load_cache(self):
        """Load cache from disk."""
        try:
            with open(self._cache_file_path, 'r', encoding='utf-8') as f:
                self._cache = json.load(f)
            print(f"[LLM] Loaded {len(self._cache)} cached classifications")
        except (json.JSONDecodeError, IOError) as e:
            print(f"[LLM] Failed to load cache: {e}")
            self._cache = {}

    def _save_cache(self):
        """Save cache to disk."""
        if not self.cache_enabled:
            return

        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(self._cache_file_path, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"[LLM] Failed to save cache: {e}")

    def classify_element(
        self,
        text: str,
        context: Dict[str, Any],
        heuristic_fallback: callable = None
    ) -> ElementClassification:
        """
        Classify a document element.

        Priority:
        1. Check cache
        2. Try LLM if enabled and available
        3. Fall back to heuristics if provided

        Args:
            text: Element text to classify
            context: Context dict with prev_element, style_name, etc.
            heuristic_fallback: Optional callable(text, context) -> str for fallback

        Returns:
            ElementClassification with type, confidence, and source
        """
        cache_key = self._make_cache_key(text, context)

        # Check cache first
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            return ElementClassification(
                element_type=cached['type'],
                confidence=cached['confidence'],
                reasoning=cached.get('reasoning', 'From cache'),
                source='cache',
                list_level=cached.get('list_level')
            )

        result = None

        # Try LLM if enabled
        if self.llm_enabled:
            client = self._get_client()
            if client.is_available():
                llm_result = client.classify_element(text, context)

                if llm_result:
                    result = ElementClassification(
                        element_type=llm_result['type'],
                        confidence=llm_result['confidence'],
                        reasoning=llm_result.get('reasoning', ''),
                        source='llm',
                        list_level=llm_result.get('list_level')
                    )

                    # Cache if confidence is high enough
                    if result.confidence >= self.confidence_threshold:
                        self._cache[cache_key] = {
                            'type': result.element_type,
                            'confidence': result.confidence,
                            'reasoning': result.reasoning,
                            'list_level': result.list_level
                        }
                        self._save_cache()

                    # Return LLM result if confident, otherwise fall through to heuristics
                    if result.confidence >= self.confidence_threshold:
                        return result

        # Fall back to heuristics
        if heuristic_fallback is not None:
            heuristic_type = heuristic_fallback(text, context)
            return ElementClassification(
                element_type=heuristic_type or 'paragraph',
                confidence=0.6,  # Moderate confidence for heuristics
                reasoning='Heuristic classification',
                source='heuristic'
            )

        # Default fallback
        return ElementClassification(
            element_type='paragraph',
            confidence=0.3,
            reasoning='Default fallback',
            source='default'
        )

    def is_llm_available(self) -> bool:
        """Check if LLM classification is available."""
        if not self.llm_enabled:
            return False
        return self._get_client().is_available()

    def get_stats(self) -> Dict[str, Any]:
        """Get classification statistics."""
        return {
            'llm_enabled': self.llm_enabled,
            'llm_available': self.is_llm_available() if self.llm_enabled else False,
            'cache_size': len(self._cache),
            'confidence_threshold': self.confidence_threshold
        }
