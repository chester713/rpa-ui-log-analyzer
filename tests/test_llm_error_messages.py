"""Model problems are reported to the user in plain language, with the real cause.

A provider answering "503: high demand" used to reach the browser as a bare
"An internal error occurred". Now the upload page, the workspace and the CLI all say
what happened, and what to do, while the full provider response stays in the server log.
"""

import io
import logging
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

import app as webapp
import src_cli
from src.inference.event_grouper import LLMGroupRefiner
from src.llm.client import LLMClient, LLMError, _describe_http_error, _provider_message
from src.parser.csv_loader import CSVLoader

ROOT = Path(__file__).resolve().parents[1]

GEMINI_503 = """[{
  "error": {
    "code": 503,
    "message": "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.",
    "status": "UNAVAILABLE"
  }
}
]"""


# ── messages built from provider responses ──────────────────────────────────

def test_overloaded_provider_is_explained_with_its_own_message() -> None:
    message = _describe_http_error(503, GEMINI_503)

    assert "temporarily overloaded or unavailable" in message
    assert "HTTP 503" in message
    assert "This model is currently experiencing high demand" in message
    assert "try again in a minute" in message
    assert "{" not in message and '"error"' not in message  # no raw JSON body


@pytest.mark.parametrize(
    "status, body, expected",
    [
        (429, '{"error": {"message": "Quota exceeded"}}', "rate limit or quota"),
        (401, "", "rejected the API key"),
        (403, '{"error": {"message": "denied"}}', "rejected the API key"),
        (404, "", "model or endpoint was not found"),
        (400, '[{"error": {"message": "API key not valid. Please pass a valid API key."}}]', "API key not valid"),
        (500, "", "temporarily overloaded or unavailable"),
        (418, "", "unexpected error"),
    ],
)
def test_other_http_failures_have_specific_advice(status, body, expected) -> None:
    message = _describe_http_error(status, body)

    assert expected in message
    assert f"HTTP {status}" in message


def test_html_error_pages_are_not_shown_to_users() -> None:
    message = _describe_http_error(502, "<html><body><h1>Bad Gateway</h1></body></html>")

    assert "<" not in message
    assert message.startswith("The language model is temporarily overloaded or unavailable (HTTP 502)")


def test_short_plain_text_bodies_are_kept() -> None:
    assert _provider_message("Service Unavailable") == "Service Unavailable"


def test_very_long_provider_messages_are_shortened() -> None:
    body = '{"error": {"message": "' + "x" * 1000 + '"}}'

    assert len(_provider_message(body)) <= 300


class _Response:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


def test_client_raises_the_plain_language_message_and_logs_the_raw_response(monkeypatch, caplog) -> None:
    monkeypatch.setattr("src.llm.client._post_with_retry", lambda *a, **k: _Response(503, GEMINI_503))
    client = LLMClient({"api_key": "test-key", "backup_model": ""})  # no backup: test the single message

    with caplog.at_level(logging.WARNING, logger="src.llm.client"):
        with pytest.raises(LLMError) as raised:
            client.complete("hello")

    assert "temporarily overloaded or unavailable" in str(raised.value)
    assert "UNAVAILABLE" not in str(raised.value)
    assert "UNAVAILABLE" in caplog.text  # the full response is kept for debugging


# ── upload page ─────────────────────────────────────────────────────────────

class _FailingLLM:
    def __init__(self, error):
        self.error = error

    def complete(self, prompt):
        raise self.error


@pytest.fixture
def upload(monkeypatch, tmp_path):
    """POST a file to a route with a given LLM failure; returns the response."""
    monkeypatch.setitem(webapp.app.config, "UPLOAD_FOLDER", str(tmp_path))

    def post(route, error=None, content=b"event,app\nclick,Excel\n"):
        failing = _FailingLLM(error or RuntimeError("never used"))
        monkeypatch.setattr("src.llm.client.get_llm_client", lambda *a, **k: failing)
        return webapp.app.test_client().post(
            route, data={"file": (io.BytesIO(content), "log.csv")}, content_type="multipart/form-data"
        )

    return post


def _query(response):
    return parse_qs(urlparse(response.headers["Location"]).query)


def test_select_column_shows_the_real_llm_problem_on_the_upload_page(upload) -> None:
    response = upload("/select-column", LLMError(_describe_http_error(503, GEMINI_503)))

    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/upload"
    message = _query(response)["llm_error"][0]
    assert "temporarily overloaded or unavailable" in message
    assert "HTTP 503" in message


def test_select_column_reports_a_missing_api_key_clearly(upload) -> None:
    response = upload("/select-column", LLMError("No API key configured. Set the GEMINI_API_KEY environment variable."))

    assert "GEMINI_API_KEY" in _query(response)["llm_error"][0]


def test_select_column_explains_a_file_that_is_not_utf8(upload) -> None:
    response = upload("/select-column", content=b"event,app\n\xe9,x\n")

    assert response.status_code == 302
    assert "UTF-8" in _query(response)["error"][0]


def test_select_column_keeps_unexpected_errors_generic_but_visible(upload) -> None:
    response = upload("/select-column", RuntimeError("secret internal detail"))

    assert response.status_code == 302
    message = _query(response)["error"][0]
    assert "internal error" in message
    assert "secret internal detail" not in message


def test_detect_column_api_returns_the_llm_message(upload) -> None:
    response = upload("/detect-column", LLMError(_describe_http_error(429, "")))

    assert response.status_code == 502
    body = response.get_json()
    assert body["llm_error"] is True
    assert "rate limit or quota" in body["error"]


def test_detect_column_api_keeps_unexpected_errors_generic(upload) -> None:
    response = upload("/detect-column", RuntimeError("secret internal detail"))

    assert response.status_code == 500
    assert "secret internal detail" not in response.get_data(as_text=True)


def test_upload_page_displays_both_kinds_of_message_as_text() -> None:
    template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "params.get('llm_error')" in template
    assert "params.get('error')" in template
    assert "el.textContent = message" in template


# ── workspace page ──────────────────────────────────────────────────────────

def test_workspace_shows_a_crafted_llm_error_as_text(monkeypatch) -> None:
    monkeypatch.setattr(webapp, "get_history", lambda: [{"id": "h1", "filename": "f.csv", "timestamp": "t"}])

    response = webapp.app.test_client().get("/workspace/h1?llm_error=%3Cb%20id%3Dinjected%3Ebold%3C%2Fb%3E")

    html = response.get_data(as_text=True)
    assert "&lt;b id=injected&gt;bold&lt;/b&gt;" in html
    assert "<b id=injected>" not in html


def test_workspace_escapes_error_text_before_putting_it_in_the_page() -> None:
    template = (ROOT / "templates" / "workspace.html").read_text(encoding="utf-8")

    assert "err.innerHTML = esc(msg)" in template
    assert "|safe" not in template


# ── unparseable model output ────────────────────────────────────────────────

class _Replies:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, prompt):
        return self.reply


def _context_columns(reply):
    return CSVLoader(_Replies(reply))._detect_context_columns_with_llm(["app", "url"], sample_rows=[])


def test_context_columns_reply_that_is_not_json_gets_a_readable_error() -> None:
    with pytest.raises(LLMError) as raised:
        _context_columns("Sure! The application column is app.")

    assert "did not return valid JSON" in str(raised.value)
    assert "Please try again" in str(raised.value)


@pytest.mark.parametrize("reply", ["[1, 2]", '{"switch_columns": "app", "group_columns": []}'])
def test_context_columns_reply_with_the_wrong_shape_gets_a_readable_error(reply) -> None:
    with pytest.raises(LLMError, match="unexpected format"):
        _context_columns(reply)


def test_context_columns_reply_in_a_code_fence_still_works() -> None:
    result = _context_columns('```json\n{"switch_columns": ["app"], "group_columns": ["url"]}\n```')

    assert result["switch_columns"] == ["app"]
    assert result["group_columns"] == ["url", "app"]


def test_refinement_reply_with_malformed_json_gets_a_readable_error() -> None:
    with pytest.raises(ValueError, match="malformed JSON for group refinement"):
        LLMGroupRefiner(None)._parse_response("[[0], [1,]]", 2)


# ── CLI ─────────────────────────────────────────────────────────────────────

def test_cli_reports_llm_problems_as_errors_not_unexpected_errors(monkeypatch, capsys) -> None:
    failing = _FailingLLM(LLMError(_describe_http_error(503, GEMINI_503)))
    monkeypatch.setattr(src_cli, "get_llm_client", lambda *a, **k: failing)
    monkeypatch.setattr(sys, "argv", ["src_cli.py", str(ROOT / "sample.csv")])

    with pytest.raises(SystemExit) as exit_info:
        src_cli.main()

    assert exit_info.value.code == 1
    stderr = capsys.readouterr().err
    assert stderr.startswith("Error: The language model is temporarily overloaded or unavailable")
    assert "Unexpected error" not in stderr
