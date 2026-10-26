"""LLM client for activity inference and column detection."""

import json
import logging
import os
import time

_logger = logging.getLogger(__name__)

_TIMEOUT = 30
_MAX_TOKENS = 2000
_MAX_RETRIES = 2
_RETRY_BACKOFF = 1  # seconds; doubles on each retry
# Statuses that mean the provider is busy or briefly unavailable rather than that the
# request or the key is wrong. They are retried, and only they allow the switch to the
# backup model.
_TEMPORARY_STATUSES = (429, 500, 502, 503, 504)

# Bundled hosted LLM. The app ships with its own provider so users never have to
# supply an API key — every analysis uses this Gemini model by default. Config
# values, when present, override these; otherwise these are used as-is.
_DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
# The key is never hardcoded in source. It is read from the GEMINI_API_KEY
# environment variable, or from the git-ignored config/llm_config.json (which
# overrides this default). If neither is set, complete() raises a clear LLMError.
_DEFAULT_API_KEY = os.environ.get("GEMINI_API_KEY", "")
_DEFAULT_MODEL = "gemini-3.1-flash-lite"
# Backup model: same endpoint and key. Used only if an analysis's first LLM task cannot
# be completed by the main model because of a temporary provider problem (see LLMClient).
_DEFAULT_BACKUP_MODEL = "gemini-3.5-flash-lite"


class LLMError(RuntimeError):
    """Raised when an LLM request fails or returns nothing usable.

    The pipeline has no rule-based fallback by design: a failed LLM call is
    surfaced to the user instead of being silently substituted, so a broken
    request can never masquerade as a real (false-positive) result.

    ``temporary`` is True for provider-side problems that may pass (overload, rate
    limit, timeouts). Only those can trigger the switch to the backup model; a wrong
    key or a rejected request would fail on the backup too.
    """

    def __init__(self, message: str, temporary: bool = False):
        super().__init__(message)
        self.temporary = temporary


def _provider_message(body: str) -> str | None:
    """The human-readable message inside a provider's error body, if there is one.

    Handles an object ({"error": {"message": ...}}) or a one-element list of them,
    which is how the Gemini endpoint answers. Short plain text is passed through;
    HTML error pages are ignored.
    """
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        data = None
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        error = data.get("error", data)
        message = error.get("message") if isinstance(error, dict) else error
        if isinstance(message, str) and message.strip():
            text = " ".join(message.split())
            return text if len(text) <= 300 else text[:297] + "..."
        return None
    text = " ".join((body or "").split())
    if text and "<" not in text and len(text) <= 160:
        return text
    return None


def _describe_http_error(status: int, body: str) -> str:
    """Turn a failed HTTP response into a message a user can act on.

    The full response is written to the server log by the caller; the message
    shown to users keeps the provider's own explanation but not the raw body.
    """
    detail = _provider_message(body)
    if status in (500, 502, 503, 504):
        headline = "The language model is temporarily overloaded or unavailable"
        advice = "This is on the provider's side and usually passes; please try again in a minute."
    elif status == 429:
        headline = "The language model's rate limit or quota was reached"
        advice = "Wait a minute and try again, or check the quota of the API key."
    elif status in (401, 403):
        headline = "The language model rejected the API key"
        advice = (
            "Check GEMINI_API_KEY (or api_key in config/llm_config.json) "
            "and that the key may use this model."
        )
    elif status == 404:
        headline = "The configured language model or endpoint was not found"
        advice = "Check the model name and endpoint in config/llm_config.json."
    elif status == 400:
        headline = "The language model rejected the request"
        advice = "If the details mention the API key, check GEMINI_API_KEY."
    else:
        headline = "The language model returned an unexpected error"
        advice = "Please try again."
    shown = f"HTTP {status}: {detail.rstrip('.')}" if detail else f"HTTP {status}"
    return f"{headline} ({shown}). {advice}"


def _post_with_retry(url: str, payload: dict, headers: dict) -> "requests.Response":
    """POST with exponential backoff on timeouts, connection errors and temporary statuses."""
    import requests

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
            if response.status_code in _TEMPORARY_STATUSES and attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF * (2 ** attempt)
                _logger.warning("LLM returned status %d (attempt %d/%d), retrying in %ds",
                                response.status_code, attempt + 1, _MAX_RETRIES + 1, wait)
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
    _logger.warning("LLM request failed after %d attempts: %s", _MAX_RETRIES + 1, last_exc)
    raise LLMError(
        f"The language model could not be reached or did not answer in time "
        f"({_MAX_RETRIES + 1} attempts). Check the internet connection and try again in a minute.",
        temporary=True,
    )


class LLMClient:
    """Client for an OpenAI-compatible chat-completions endpoint.

    **One model per analysis.** ``model`` starts as the configured main model. With
    failover enabled (the default), the *first* call made through the client is the
    analysis's first task — selecting the event column. If that call fails for a
    temporary provider reason, the client switches to ``backup_model`` (same endpoint
    and key) and retries the task once; from then on it stays on the model that
    answered. Later calls never switch, so an analysis is never split across models.
    ``used_backup`` reports whether the backup is in use. Requests that continue an
    analysis build their client with ``get_llm_client(model=...)`` so they stay on the
    model recorded when the analysis started.
    """

    def __init__(self, config: dict = None, allow_failover: bool = True):
        """
        Initialize LLM client.

        Args:
            config: LLM config dict with endpoint, api_key, model, backup_model
            allow_failover: Let the first call switch to the backup model. Pass False
                for a client that continues an analysis whose model is already chosen.
        """
        self.config = config or {}
        self.endpoint = self.config.get("endpoint") or _DEFAULT_ENDPOINT
        self.api_key = self.config.get("api_key") or _DEFAULT_API_KEY
        self.primary_model = self.config.get("model") or _DEFAULT_MODEL
        self.model = self.primary_model
        # An empty "backup_model" in the config turns the backup off.
        backup = self.config["backup_model"] if "backup_model" in self.config else _DEFAULT_BACKUP_MODEL
        self.backup_model = backup or None
        self._failover_armed = allow_failover

    @property
    def used_backup(self) -> bool:
        """True when this client is using a model other than the configured main model."""
        return self.model != self.primary_model

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
                fallback to a rule-based method; the failure is surfaced to the
                caller. Only the first call of a failover-enabled client may switch
                to the backup model (see the class docstring).
        """
        if not self._failover_armed:
            return self._complete(prompt)

        self._failover_armed = False  # only the first task may switch models
        try:
            return self._complete(prompt)
        except LLMError as main_error:
            if not (main_error.temporary and self.backup_model and self.backup_model != self.model):
                raise
            main_model = self.model
            _logger.warning(
                "Model %s is unavailable (%s); switching to backup model %s for this analysis",
                main_model, main_error, self.backup_model,
            )
            self.model = self.backup_model
            try:
                return self._complete(prompt)
            except LLMError as backup_error:
                backup_model, self.model = self.model, main_model
                raise LLMError(
                    f"Neither language model could be used. Main model {main_model}: {main_error} "
                    f"Backup model {backup_model}: {backup_error}",
                    temporary=True,
                ) from backup_error

    def _complete(self, prompt: str) -> str:
        """One request to the current model (with the retries of ``_post_with_retry``)."""
        if not self.api_key:
            raise LLMError(
                "No API key configured. Set the GEMINI_API_KEY environment variable "
                "(or api_key in config/llm_config.json)."
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
            _logger.warning(
                "LLM endpoint returned status %s for model %s: %s",
                response.status_code, self.model, response.text[:500],
            )
            raise LLMError(
                _describe_http_error(response.status_code, response.text),
                temporary=response.status_code in _TEMPORARY_STATUSES,
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"LLM returned an unexpected response format: {exc}")

        if not content or not content.strip():
            raise LLMError("LLM returned an empty response.")
        return content


def get_llm_client(
    config_path: str = "config/llm_config.json",
    model: str | None = None,
    allow_failover: bool | None = None,
) -> LLMClient:
    """
    Load LLM client from config file.

    Args:
        config_path: Path to LLM config JSON
        model: The model an analysis has already settled on (recorded when its first
            task ran). When given, the client uses it and never switches models; when
            omitted the client starts on the configured main model and may switch to
            the backup model on its first call.
        allow_failover: Override whether the first call may switch to the backup model.
            Defaults to True only when no ``model`` is given. Steps that continue an
            analysis pass False so they stay on one model even if none was recorded.

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

    if allow_failover is None:
        allow_failover = model is None
    client = LLMClient(config, allow_failover=allow_failover)
    if model:
        client.model = model
    return client
