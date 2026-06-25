"""LLM client for activity inference and column detection."""

import logging
import os
import json
import time
from typing import Optional

_logger = logging.getLogger(__name__)

_TIMEOUT = 30
_MAX_TOKENS = 2000
_MAX_RETRIES = 2
_RETRY_BACKOFF = 1  # seconds; doubles on each retry

# Bundled hosted LLM. The app ships with its own provider so users never have to
# supply an API key — every analysis uses this Gemini model by default. Config
# values, when present, override these; otherwise these are used as-is.
_DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
# The key is never hardcoded in source. It is read from the GEMINI_API_KEY
# environment variable, or from the git-ignored config/llm_config.json (which
# overrides this default). If neither is set, complete() raises a clear LLMError.
_DEFAULT_API_KEY = os.environ.get("GEMINI_API_KEY", "")
_DEFAULT_MODEL = "gemini-3.1-flash-lite"


class LLMError(RuntimeError):
    """Raised when an LLM request fails or returns nothing usable.

    The pipeline has no rule-based fallback by design: a failed LLM call is
    surfaced to the user instead of being silently substituted, so a broken
    request can never masquerade as a real (false-positive) result.
    """


def _post_with_retry(url: str, payload: dict, headers: dict) -> "requests.Response":
    """POST with exponential backoff on timeout/connection errors and 429 rate limits."""
    import requests

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
            if response.status_code == 429 and attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF * (2 ** attempt)
                _logger.warning("LLM rate limited (attempt %d/%d), retrying in %ds",
                                attempt + 1, _MAX_RETRIES + 1, wait)
                time.sleep(wait)
                continue
            return response
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF * (2 ** attempt)
                _logger.warning("LLM request failed (attempt %d/%d), retrying in %ds: %s",
                                attempt + 1, _MAX_RETRIES + 1, wait, exc)
                time.sleep(wait)
    raise LLMError(
        f"LLM request failed after {_MAX_RETRIES + 1} attempt(s): {last_exc}"
    )


class LLMClient:
    """Client for an OpenAI-compatible chat-completions endpoint."""

    def __init__(self, config: dict = None):
        """
        Initialize LLM client.

        Args:
            config: LLM config dict with endpoint, api_key, model
        """
        self.config = config or {}
        self.endpoint = self.config.get("endpoint") or _DEFAULT_ENDPOINT
        self.api_key = self.config.get("api_key") or _DEFAULT_API_KEY
        self.model = self.config.get("model") or _DEFAULT_MODEL

    def complete(self, prompt: str) -> str:
        """
        Send prompt to the LLM and return the completion text.

        Args:
            prompt: The prompt to send

        Returns:
            Completion text

        Raises:
            LLMError: On any failure — missing key, transport error, non-200
                status, malformed body, or empty completion. There is no
                fallback; the failure is surfaced to the caller.
        """
        if not self.api_key:
            raise LLMError(
                "No API key configured. Add one in Settings or config/llm_config.json."
            )

        endpoint = self.endpoint or _DEFAULT_ENDPOINT
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": _MAX_TOKENS,
            "temperature": 0,
        }

        response = _post_with_retry(endpoint, payload, headers)
        if response.status_code != 200:
            raise LLMError(
                f"LLM endpoint returned status {response.status_code}: "
                f"{response.text[:200]}"
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"LLM returned an unexpected response format: {exc}")

        if not content or not content.strip():
            raise LLMError("LLM returned an empty response.")
        return content


def get_llm_client(config_path: str = "config/llm_config.json") -> Optional[LLMClient]:
    """
    Load LLM client from config file.

    Args:
        config_path: Path to LLM config JSON

    Returns:
        LLMClient instance. The app bundles its own hosted provider, so a client
        is always returned even when no config file exists: missing fields fall
        back to the bundled Gemini endpoint, key, and model. Any values present
        in the config file override the bundled defaults.
    """
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    return LLMClient(config)
