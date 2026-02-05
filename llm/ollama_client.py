"""
Ollama API client for LLM-based document structure classification.
"""

import json
import urllib.request
import urllib.error
from typing import Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class OllamaResponse:
    """Response from Ollama API."""
    content: str
    model: str
    done: bool
    total_duration: Optional[int] = None
    eval_count: Optional[int] = None


class OllamaClient:
    """
    HTTP client for Ollama API.

    Supports configurable URL and model for connecting to local or remote Ollama instances.
    """

    def __init__(self, url: str = "http://localhost:11434", model: str = "gemma3:4b-it-qat"):
        """
        Initialize Ollama client.

        Args:
            url: Base URL for Ollama API (e.g., http://localhost:11434)
            model: Model name to use for generation (e.g., gemma3:4b-it-qat)
        """
        self.url = url.rstrip('/')
        self.model = model
        self._available = None

    def is_available(self) -> bool:
        """
        Check if Ollama service is available.

        Returns:
            True if Ollama is reachable and model is available
        """
        if self._available is not None:
            return self._available

        try:
            # Try to list models
            req = urllib.request.Request(f"{self.url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                models = [m['name'] for m in data.get('models', [])]
                # Check if our model is available (with or without tag)
                model_base = self.model.split(':')[0]
                self._available = any(model_base in m for m in models)
                if not self._available:
                    print(f"[LLM] Model {self.model} not found. Available: {models}")
                return self._available
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            print(f"[LLM] Ollama not available at {self.url}: {e}")
            self._available = False
            return False

    def generate(self, prompt: str, system: Optional[str] = None,
                 temperature: float = 0.1, max_tokens: int = 500) -> Optional[OllamaResponse]:
        """
        Generate completion from Ollama.

        Args:
            prompt: User prompt
            system: Optional system message
            temperature: Sampling temperature (lower = more deterministic)
            max_tokens: Maximum tokens to generate

        Returns:
            OllamaResponse or None if request failed
        """
        if not self.is_available():
            return None

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }

        if system:
            payload["system"] = system

        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                f"{self.url}/api/generate",
                data=data,
                headers={'Content-Type': 'application/json'}
            )

            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode('utf-8'))
                return OllamaResponse(
                    content=result.get('response', ''),
                    model=result.get('model', self.model),
                    done=result.get('done', True),
                    total_duration=result.get('total_duration'),
                    eval_count=result.get('eval_count')
                )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            print(f"[LLM] Ollama request failed: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"[LLM] Invalid JSON response: {e}")
            return None

    def classify_element(self, text: str, context: Dict[str, Any]) -> Optional[Dict]:
        """
        Classify a document element using LLM.

        Args:
            text: Element text to classify
            context: Context dict with prev_element, section_name, etc.

        Returns:
            Classification dict with type, confidence, reasoning or None if failed
        """
        from .prompts import get_classification_prompt, get_system_prompt

        prompt = get_classification_prompt(text, context)
        system = get_system_prompt()

        response = self.generate(prompt, system=system, temperature=0.1, max_tokens=300)

        if response is None:
            return None

        # Parse JSON response
        try:
            # Try to extract JSON from response
            content = response.content.strip()

            # Handle case where response contains text before/after JSON
            json_start = content.find('{')
            json_end = content.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json.loads(json_str)

                # Normalize type names
                element_type = result.get('type', 'PARAGRAPH').upper()
                type_mapping = {
                    'HEADER': 'header',
                    'LIST_ITEM': 'list_item',
                    'PARAGRAPH': 'paragraph',
                    'TABLE_INTRO': 'table_intro'
                }

                return {
                    'type': type_mapping.get(element_type, 'paragraph'),
                    'confidence': float(result.get('confidence', 0.5)),
                    'reasoning': result.get('reasoning', ''),
                    'list_level': result.get('list_level')
                }
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"[LLM] Failed to parse classification response: {e}")
            print(f"[LLM] Response was: {response.content[:200]}")

        return None
