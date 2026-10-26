"""One model per analysis: the first task may switch to the backup model, then nothing switches.

The first LLM task of an analysis is selecting the event column. If the main model cannot
complete it because of a temporary provider problem, that task is retried on the backup
model, and every later step of the analysis stays on whichever model answered. The model
is recorded and shown with the analysis. A wrong key or a rejected request never switches.
"""

import io
import json
import re
import uuid

import pytest
import requests

import app as webapp
from src.llm.client import (
    _DEFAULT_BACKUP_MODEL,
    _DEFAULT_MODEL,
    LLMClient,
    LLMError,
    _post_with_retry,
    get_llm_client,
)
from src.pipeline.data_pipeline import DataPipeline, PipelineResult

MAIN = _DEFAULT_MODEL
BACKUP = _DEFAULT_BACKUP_MODEL

BUSY_BODY = '[{"error": {"code": 503, "message": "This model is currently experiencing high demand."}}]'


class _Response:
    def __init__(self, status_code, text="", content=None):
        self.status_code = status_code
        self.text = text
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def ok(content="answer"):
    return _Response(200, content=content)


def busy():
    return _Response(503, BUSY_BODY)


class _Scripted:
    """Stands in for the HTTP layer: replies per model, recording the model of every request."""

    def __init__(self, replies):
        self.replies = {model: list(items) for model, items in replies.items()}
        self.models = []

    def __call__(self, url, payload, headers):
        model = payload["model"]
        self.models.append(model)
        queue = self.replies[model]
        return queue.pop(0) if len(queue) > 1 else queue[0]


@pytest.fixture
def http(monkeypatch):
    def install(replies):
        scripted = _Scripted(replies)
        monkeypatch.setattr("src.llm.client._post_with_retry", scripted)
        return scripted

    return install


def client(**config):
    return LLMClient({"api_key": "test-key", **config})


# ── defaults and configuration ──────────────────────────────────────────────

def test_defaults_name_the_main_and_the_backup_model() -> None:
    assert MAIN == "gemini-3.1-flash-lite"
    assert BACKUP == "gemini-3.5-flash-lite"
    c = client()
    assert (c.model, c.primary_model, c.backup_model) == (MAIN, MAIN, BACKUP)
    assert c.used_backup is False


def test_config_can_change_or_disable_the_backup() -> None:
    assert client(backup_model="other-model").backup_model == "other-model"
    assert client(backup_model="").backup_model is None


# ── the first task switches, once ───────────────────────────────────────────

def test_first_task_switches_to_the_backup_and_retries_there(http) -> None:
    scripted = http({MAIN: [busy()], BACKUP: [ok("from the backup")]})
    c = client()

    assert c.complete("select the event column") == "from the backup"
    assert scripted.models == [MAIN, BACKUP]
    assert c.model == BACKUP
    assert c.used_backup is True


def test_every_later_call_stays_on_the_backup(http) -> None:
    scripted = http({MAIN: [busy()], BACKUP: [ok("b")]})
    c = client()
    c.complete("first task")

    for _ in range(3):
        assert c.complete("later step") == "b"

    assert scripted.models == [MAIN, BACKUP, BACKUP, BACKUP, BACKUP]


def test_when_the_main_model_answers_the_first_task_it_is_kept(http) -> None:
    scripted = http({MAIN: [ok("m")], BACKUP: [ok("b")]})
    c = client()

    c.complete("first task")
    c.complete("later step")

    assert scripted.models == [MAIN, MAIN]
    assert c.used_backup is False


def test_a_later_failure_is_reported_not_switched(http) -> None:
    scripted = http({MAIN: [ok("m"), busy()], BACKUP: [ok("b")]})
    c = client()
    c.complete("first task")

    with pytest.raises(LLMError) as raised:
        c.complete("later step")

    assert "temporarily overloaded" in str(raised.value)
    assert scripted.models == [MAIN, MAIN]  # the backup was never asked
    assert c.model == MAIN


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_temporary_provider_problems_switch(http, status) -> None:
    scripted = http({MAIN: [_Response(status, "")], BACKUP: [ok()]})

    client().complete("first task")

    assert scripted.models == [MAIN, BACKUP]


def test_a_timeout_on_the_first_task_switches(monkeypatch) -> None:
    models = []

    def post(url, payload, headers):
        models.append(payload["model"])
        if payload["model"] == MAIN:
            raise LLMError("could not be reached", temporary=True)
        return ok("b")

    monkeypatch.setattr("src.llm.client._post_with_retry", post)

    assert client().complete("first task") == "b"
    assert models == [MAIN, BACKUP]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_key_and_request_problems_never_switch(http, status) -> None:
    scripted = http({MAIN: [_Response(status, "")], BACKUP: [ok()]})

    with pytest.raises(LLMError) as raised:
        client().complete("first task")

    assert raised.value.temporary is False
    assert scripted.models == [MAIN]


def test_a_missing_key_never_switches(http) -> None:
    scripted = http({MAIN: [ok()], BACKUP: [ok()]})
    c = LLMClient({"api_key": "", "backup_model": BACKUP})
    c.api_key = ""  # whatever the environment provides

    with pytest.raises(LLMError, match="No API key"):
        c.complete("first task")

    assert scripted.models == []


def test_no_backup_configured_means_no_switch(http) -> None:
    scripted = http({MAIN: [busy()]})

    with pytest.raises(LLMError):
        client(backup_model="").complete("first task")

    assert scripted.models == [MAIN]


def test_a_backup_equal_to_the_main_model_is_not_a_switch(http) -> None:
    scripted = http({BACKUP: [busy()]})

    with pytest.raises(LLMError):
        client(model=BACKUP, backup_model=BACKUP).complete("first task")

    assert scripted.models == [BACKUP]


def test_a_client_that_continues_an_analysis_never_switches(http) -> None:
    scripted = http({MAIN: [busy()], BACKUP: [ok()]})

    with pytest.raises(LLMError):
        LLMClient({"api_key": "k"}, allow_failover=False).complete("some step")

    assert scripted.models == [MAIN]


def test_when_both_models_fail_the_message_names_both(http) -> None:
    http({MAIN: [busy()], BACKUP: [busy()]})
    c = client()

    with pytest.raises(LLMError) as raised:
        c.complete("first task")

    message = str(raised.value)
    assert "Neither language model could be used" in message
    assert f"Main model {MAIN}" in message and f"Backup model {BACKUP}" in message
    assert "temporarily overloaded" in message
    assert c.model == MAIN  # not left on a model that did not answer


# ── retries and the temporary flag ──────────────────────────────────────────

def test_temporary_server_errors_are_retried_with_backoff(monkeypatch) -> None:
    replies = [busy(), busy(), ok("fine")]
    sleeps = []
    monkeypatch.setattr("requests.post", lambda *a, **k: replies.pop(0))
    monkeypatch.setattr("src.llm.client.time.sleep", sleeps.append)

    response = _post_with_retry("http://example.test", {}, {})

    assert response.status_code == 200
    assert sleeps == [1, 2]


def test_a_rejected_request_is_not_retried(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("requests.post", lambda *a, **k: calls.append(1) or _Response(401, ""))
    monkeypatch.setattr("src.llm.client.time.sleep", lambda s: None)

    assert _post_with_retry("http://example.test", {}, {}).status_code == 401
    assert len(calls) == 1


def test_a_persistent_outage_is_returned_after_the_retries(monkeypatch) -> None:
    monkeypatch.setattr("requests.post", lambda *a, **k: busy())
    monkeypatch.setattr("src.llm.client.time.sleep", lambda s: None)

    assert _post_with_retry("http://example.test", {}, {}).status_code == 503


def test_repeated_timeouts_become_a_temporary_plain_language_error(monkeypatch) -> None:
    def post(*a, **k):
        raise requests.exceptions.Timeout("read timed out")

    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr("src.llm.client.time.sleep", lambda s: None)

    with pytest.raises(LLMError) as raised:
        _post_with_retry("http://example.test", {}, {})

    assert raised.value.temporary is True
    assert "could not be reached or did not answer in time" in str(raised.value)
    assert "read timed out" not in str(raised.value)  # the detail stays in the log


# ── get_llm_client ──────────────────────────────────────────────────────────

def _config(tmp_path, **values):
    path = tmp_path / "llm_config.json"
    path.write_text(json.dumps({"api_key": "k", **values}), encoding="utf-8")
    return str(path)


def test_a_new_analysis_starts_on_the_main_model_and_may_switch(http, tmp_path) -> None:
    scripted = http({MAIN: [busy()], BACKUP: [ok("b")]})

    c = get_llm_client(_config(tmp_path))
    c.complete("first task")

    assert scripted.models == [MAIN, BACKUP]


def test_a_continuing_analysis_stays_on_its_recorded_model(http, tmp_path) -> None:
    scripted = http({BACKUP: [busy()], MAIN: [ok()]})

    c = get_llm_client(_config(tmp_path), model=BACKUP)

    assert c.model == BACKUP and c.used_backup is True
    with pytest.raises(LLMError):
        c.complete("later step")
    assert scripted.models == [BACKUP]  # no switch back to the main model


def test_failover_can_be_switched_off_without_naming_a_model(http, tmp_path) -> None:
    scripted = http({MAIN: [busy()], BACKUP: [ok()]})

    c = get_llm_client(_config(tmp_path), allow_failover=False)

    assert c.model == MAIN
    with pytest.raises(LLMError):
        c.complete("some step")
    assert scripted.models == [MAIN]


# ── web: the first task at upload decides the model for the whole analysis ──

def _upload(monkeypatch, tmp_path, route="/select-column"):
    monkeypatch.setitem(webapp.app.config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr("src.llm.client.get_llm_client", lambda *a, **k: LLMClient({"api_key": "k"}))
    web = webapp.app.test_client()
    response = web.post(
        route, data={"file": (io.BytesIO(b"event,app\nclick,Excel\n"), "log.csv")},
        content_type="multipart/form-data",
    )
    return web, response


def test_upload_records_the_backup_when_the_first_task_switched(http, monkeypatch, tmp_path) -> None:
    scripted = http({MAIN: [busy()], BACKUP: [ok("event")]})

    web, response = _upload(monkeypatch, tmp_path)

    assert response.status_code == 200
    assert scripted.models == [MAIN, BACKUP]
    with web.session_transaction() as session:
        assert session["llm_model"] == BACKUP
        assert session["llm_backup_used"] is True


def test_upload_records_the_main_model_when_it_answers(http, monkeypatch, tmp_path) -> None:
    http({MAIN: [ok("event")], BACKUP: [ok("event")]})

    web, _ = _upload(monkeypatch, tmp_path)

    with web.session_transaction() as session:
        assert session["llm_model"] == MAIN
        assert session["llm_backup_used"] is False


def test_the_json_upload_route_records_it_too(http, monkeypatch, tmp_path) -> None:
    http({MAIN: [busy()], BACKUP: [ok("event")]})

    web, response = _upload(monkeypatch, tmp_path, route="/detect-column")

    assert response.status_code == 200
    with web.session_transaction() as session:
        assert session["llm_model"] == BACKUP


def test_when_both_models_fail_the_upload_page_says_so(http, monkeypatch, tmp_path) -> None:
    http({MAIN: [busy()], BACKUP: [busy()]})

    web, response = _upload(monkeypatch, tmp_path)

    assert response.status_code == 302
    assert "Neither+language+model" in response.headers["Location"] or "Neither%20language%20model" in response.headers["Location"]
    with web.session_transaction() as session:
        assert "llm_model" not in session


class _AnalysisLLM:
    """Answers prompts P1-P4 for a tiny log; reports the model it was given."""

    def __init__(self, model):
        self.model = model
        self.used_backup = model != MAIN

    def complete(self, prompt):
        if "selecting the activity-name attribute" in prompt:  # P1
            return "Event"
        if '"environment_attributes"' in prompt:  # P2
            return json.dumps({
                "switch_attributes": ["Application"],
                "group_attributes": ["Application"],
                "environment_attributes": {"web": [], "desktop": ["Application"], "screen": []},
                "element_attributes": [],
            })
        if "grouping UI events into UI activities" in prompt:  # P3: one UI activity per event
            events = re.findall(r"^\s+\[(\d+)\] (\S+)", prompt, re.M)
            return json.dumps([[int(number)] for number, _ in events])
        if "RPA (Robotic Process Automation) designer" in prompt:  # P4
            groups = prompt.split("\nGROUP ")[1:]
            return json.dumps([
                {"activity_name": f"Activate button {i} in Excel", "pattern": "Activate",
                 "target": f"button {i}", "context": "in Excel",
                 "evidence": ["e"], "confidence": 0.9, "reasoning": "r"}
                for i, _ in enumerate(groups)
            ])
        raise AssertionError("unexpected prompt: " + prompt[:80])


@pytest.fixture
def analysis(monkeypatch, tmp_path):
    """Run start-progressive for an upload whose recorded model is given; capture client requests."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.web.step_store._STORE_DIR", str(tmp_path / "progressive"))
    history = []
    monkeypatch.setattr("src.web.progressive._get_history", lambda: history)
    monkeypatch.setattr("src.web.progressive._save_history", lambda h: None)
    requests_made = []

    def factory(*args, model=None, allow_failover=None, **kwargs):
        requests_made.append({"model": model, "allow_failover": allow_failover})
        return _AnalysisLLM(model or MAIN)

    monkeypatch.setattr("src.llm.client.get_llm_client", factory)
    csv_path = tmp_path / "upload.csv"
    csv_path.write_text("Event,Application\nclick,Excel\npaste,Excel\n", encoding="utf-8")

    def run(recorded_model, backup_used):
        web = webapp.app.test_client()
        with web.session_transaction() as session:
            session["uploaded_file"] = str(csv_path)
            session["filename"] = "upload.csv"
            if recorded_model:
                session["llm_model"] = recorded_model
                session["llm_backup_used"] = backup_used
        response = web.get("/p/start-progressive?event_column=Event")
        assert response.status_code == 302
        return history[0]

    return run, requests_made


def test_every_step_of_the_analysis_uses_the_model_recorded_at_upload(analysis) -> None:
    from src.web import progressive
    from src.web.step_store import StepStore

    run, requests_made = analysis

    entry = run(BACKUP, True)
    aid = entry["progressive_aid"]
    progressive._step2_progress[aid] = {"status": "computing", "completed": 0, "total": 0}
    progressive._run_step2_thread(aid)

    assert progressive._step2_progress[aid]["status"] == "done"
    assert entry["llm_model"] == BACKUP and entry["llm_backup_used"] is True
    assert StepStore(aid).load("meta")["llm_model"] == BACKUP
    assert requests_made == [
        {"model": BACKUP, "allow_failover": None},   # step 1: stays on the recorded model
        {"model": BACKUP, "allow_failover": False},  # step 2: stays, and can never switch
    ]


def test_an_analysis_that_started_on_the_main_model_stays_on_it(analysis) -> None:
    run, requests_made = analysis

    entry = run(MAIN, False)

    assert entry["llm_model"] == MAIN and entry["llm_backup_used"] is False
    assert requests_made[0]["model"] == MAIN


def test_without_a_recorded_model_step_one_decides_and_step_two_follows(analysis) -> None:
    from src.web import progressive
    from src.web.step_store import StepStore

    run, requests_made = analysis

    entry = run(None, False)
    aid = entry["progressive_aid"]
    progressive._step2_progress[aid] = {"status": "computing", "completed": 0, "total": 0}
    progressive._run_step2_thread(aid)

    assert requests_made[0] == {"model": None, "allow_failover": None}  # armed: step 1 may switch
    assert requests_made[1] == {"model": MAIN, "allow_failover": False}  # step 2 follows what step 1 used
    assert StepStore(aid).load("meta")["llm_model"] == MAIN


def test_an_older_analysis_without_a_model_never_switches_in_step_two(analysis) -> None:
    from src.web import progressive
    from src.web.step_store import StepStore

    run, requests_made = analysis
    entry = run(MAIN, False)
    aid = entry["progressive_aid"]
    store = StepStore(aid)
    meta = store.load("meta")
    meta.pop("llm_model")
    meta.pop("llm_backup_used")
    store.save("meta", meta)
    requests_made.clear()

    progressive._step2_progress[aid] = {"status": "computing", "completed": 0, "total": 0}
    progressive._run_step2_thread(aid)

    assert requests_made == [{"model": None, "allow_failover": False}]


# ── CLI ─────────────────────────────────────────────────────────────────────

def test_cli_pipeline_records_the_model_that_produced_the_result(tmp_path) -> None:
    csv_path = tmp_path / "log.csv"
    csv_path.write_text("Event,Application\nclick,Excel\npaste,Excel\n", encoding="utf-8")
    llm = _AnalysisLLM(BACKUP)

    result = DataPipeline(str(csv_path), llm_client=llm).run()

    assert result.statistics["llm_model"] == BACKUP
    assert result.statistics["llm_backup_used"] is True
    summary = result.summary()
    assert f"Model: {BACKUP} (backup model; the main model was unavailable)" in summary


def test_cli_summary_names_the_main_model_without_a_note() -> None:
    result = PipelineResult([], [], [], {"llm_model": MAIN, "llm_backup_used": False})

    assert f"Model: {MAIN}\n" in result.summary()
    assert "backup" not in result.summary()


def test_cli_summary_has_no_model_line_when_it_is_unknown() -> None:
    assert "Model:" not in PipelineResult([], [], [], {}).summary()


# ── pages show which model produced an analysis ─────────────────────────────

def _entry(**extra):
    entry = {
        "id": "h1", "timestamp": "2026-10-26T09:00:00", "filename": "log.csv", "event_column": "event",
        "activities": ["A"], "recommendations": [], "dfg": {}, "log_columns": ["event"],
        "log_preview": [{"row_index": 0, "values": {"event": "click"}}],
        "progressive_artifacts": {
            k: {} for k in ("event_grouping", "activity_naming", "action_object_extraction",
                            "pattern_matching", "context_determination", "method_recommendation")
        },
        "progressive_logic": {}, "progressive_aid": "aid",
    }
    entry.update(extra)
    return entry


def _html(monkeypatch, path, entries):
    monkeypatch.setattr(webapp, "get_history", lambda: entries)
    response = webapp.app.test_client().get(path)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_workspace_header_shows_the_model_and_marks_the_backup(monkeypatch) -> None:
    backup = _html(monkeypatch, "/workspace/h1", [_entry(llm_model=BACKUP, llm_backup_used=True)])
    main = _html(monkeypatch, "/workspace/h1", [_entry(llm_model=MAIN, llm_backup_used=False)])
    legacy = _html(monkeypatch, "/workspace/h1", [_entry()])

    assert f"Model: {BACKUP} (backup model)" in backup
    assert f"Model: {MAIN}" in main and "(backup model)" not in main
    assert "Model:" not in legacy


def test_results_header_shows_the_model_and_marks_the_backup(monkeypatch) -> None:
    recommendation = {"inferred_activity": "A", "events": [0], "execution_environment": "web", "method": "x"}
    backup = _html(monkeypatch, "/results/h1", [_entry(llm_model=BACKUP, llm_backup_used=True, recommendations=[recommendation])])
    main = _html(monkeypatch, "/results/h1", [_entry(llm_model=MAIN, llm_backup_used=False, recommendations=[recommendation])])

    assert f"Model: {BACKUP} (backup model)" in backup
    assert f"Model: {MAIN}" in main and "(backup model)" not in main


def test_history_table_has_a_model_column(monkeypatch) -> None:
    html = _html(monkeypatch, "/history", [
        _entry(id="a", llm_model=BACKUP, llm_backup_used=True),
        _entry(id="b", llm_model=MAIN, llm_backup_used=False),
        _entry(id="c"),
    ])

    assert "<th>Model</th>" in html
    assert f"{BACKUP} (backup)" in html
    assert f"<td>{MAIN}</td>" in html
    assert "<td>—</td>" in html  # an analysis from before models were recorded
