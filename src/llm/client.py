"""LLM client for activity inference and column detection."""

import os
import json
from typing import Optional, Any


class LLMClient:
    """Client for LLM API calls with multiple provider support."""

    def __init__(self, config: dict = None):
        """
        Initialize LLM client.

        Args:
            config: LLM config dict with provider, endpoint, api_key, model
        """
        self.config = config or {}
        self.provider = self.config.get("provider", "puter")
        self.endpoint = self.config.get("endpoint", "")
        self.api_key = self.config.get("api_key", "")
        self.model = self.config.get("model", "gpt-4o-mini")

    def complete(self, prompt: str) -> str:
        """
        Send prompt to LLM and get completion.

        Args:
            prompt: The prompt to send

        Returns:
            Completion text
        """
        if self.provider == "puter":
            return self._complete_puter(prompt)
        elif self.provider == "custom":
            return self._complete_custom(prompt)
        else:
            return self._complete_puter(prompt)

    def _complete_puter(self, prompt: str) -> str:
        """Use Puter.js for free LLM."""
        import requests

        url = "https://api.puter.ai/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return (
                    data.get("choices", [{}])[0].get("message", {}).get("content", "")
                )
        except Exception:
            pass

        return ""

    def _complete_custom(self, prompt: str) -> str:
        """Use custom OpenAI-compatible API."""
        import requests

        if not self.api_key:
            return ""

        endpoint = self.endpoint or "https://api.openai.com/v1/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
        }

        try:
            response = requests.post(
                endpoint, json=payload, headers=headers, timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                return (
                    data.get("choices", [{}])[0].get("message", {}).get("content", "")
                )
        except Exception:
            pass

        return ""


def get_llm_client(config_path: str = "config/llm_config.json") -> Optional[LLMClient]:
    """
    Load LLM client from config file.

    Args:
        config_path: Path to LLM config JSON

    Returns:
        LLMClient instance or None
    """
    if not os.path.exists(config_path):
        return None

    with open(config_path, "r") as f:
        config = json.load(f)

    if config.get("provider") == "puter" and not config.get("api_key"):
        return LLMClient(config)

    if config.get("api_key"):
        return LLMClient(config)

    return None
