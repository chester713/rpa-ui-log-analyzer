"""Contract tests for the live progressive pipeline.

These replace the old test_analyze_*.py contract tests, which drove the
removed /analyze route. They seed a StepStore with deterministic step 1/2
fixtures and drive the real /p/<aid>/compute/<stage> endpoint, exercising
the genuine compute_step3/4/6, DFG build, and history persistence.
"""

from __future__ import annotations

import uuid

import app as webapp


REQUIRED_STAGES = [
    "event_grouping",
    "activity_naming",
    "action_object_extraction",
    "pattern_matching",
    "context_determination",
    "method_recommendation",
]


_STEP1 = {
    "groups": [
        {
            "group_index": 0,
            "events": [
                {
                    "event": "click",
                    "row_index": 0,
                    "attributes": {"browser_url": "https://example.test", "tag_name": "button"},
                }
            ],
            "is_context_switch": False,
            "previous_app": None,
            "current_app": None,
        },
        {
            "group_index": 1,
            "events": [
                {
                    "event": "read",
                    "row_index": 1,
                    "attributes": {"browser_url": "https://example.test", "tag_name": "span"},
                }
            ],
            "is_context_switch": False,
            "previous_app": None,
            "current_app": None,
        },
    ],
    "group_count": 2,
    "event_count": 2,
}

_STEP2 = {
    "activities": [
        {
            "name": "Activate login button",
            "confidence": 0.9,
            "evidence": ["clicked button"],
            "reasoning": "user clicked the login button",
            "source_events": [0],
            "activity_type": "main",
            "is_implicit": False,
            "group_index": 0,
            "pattern_name": "Activate",
        },
        {
            "name": "Read account balance",
            "confidence": 0.9,
            "evidence": ["read span"],
            "reasoning": "user read the balance",
            "source_events": [1],
            "activity_type": "main",
            "is_implicit": False,
            "group_index": 1,
            "pattern_name": "Read Element",
        },
    ]
}


def _seed(monkeypatch, tmp_path):
    """Seed a StepStore + in-memory history entry; return (aid, entry, client)."""
    monkeypatch.setattr("src.web.step_store._STORE_DIR", str(tmp_path / "progressive"))

    from src.web.step_store import StepStore

    aid = str(uuid.uuid4())
    history_id = str(uuid.uuid4())

    store = StepStore(aid)
    store.save("meta", {
        "aid": aid,
        "history_id": history_id,
        "filename": "sample.csv",
        "filepath": str(tmp_path / "sample.csv"),
        "event_column": "Event",
    })
    store.save_step(1, _STEP1)
    store.save_step(2, _STEP2)

    entry = {
        "id": history_id,
        "filename": "sample.csv",
        "progressive_artifacts": {k: {} for k in REQUIRED_STAGES},
        "progressive_logic": {k: f"logic {k}" for k in REQUIRED_STAGES},
        "dfg": {},
        "progressive_aid": aid,
    }
    history = [entry]
    # Same list object across calls so in-place mutations by the endpoint persist.
    monkeypatch.setattr("src.web.progressive._get_history", lambda: history)
    monkeypatch.setattr("src.web.progressive._save_history", lambda h: None)

    return aid, entry, webapp.app.test_client()


def _compute_to_end(client, aid):
    resp = client.get(f"/p/{aid}/compute/method_recommendation")
    # The endpoint redirects to the workspace on success.
    assert resp.status_code in (301, 302), resp.status_code
    return resp


def test_progressive_artifacts_expose_all_six_stages_in_fixed_order(monkeypatch, tmp_path) -> None:
    aid, entry, client = _seed(monkeypatch, tmp_path)

    _compute_to_end(client, aid)

    assert list(entry["progressive_artifacts"].keys()) == REQUIRED_STAGES
    assert list(entry["progressive_logic"].keys()) == REQUIRED_STAGES


def test_progressive_persists_all_computed_stage_artifacts(monkeypatch, tmp_path) -> None:
    aid, entry, client = _seed(monkeypatch, tmp_path)

    _compute_to_end(client, aid)

    artifacts = entry["progressive_artifacts"]
    # Stages computed by the endpoint must now carry real data, not empty stubs.
    assert artifacts["action_object_extraction"].get("pairs")
    assert artifacts["pattern_matching"].get("matches")
    assert artifacts["context_determination"].get("contexts")
    assert artifacts["method_recommendation"].get("recommendations")


def test_progressive_builds_dfg_with_expected_fields(monkeypatch, tmp_path) -> None:
    aid, entry, client = _seed(monkeypatch, tmp_path)

    _compute_to_end(client, aid)

    dfg = entry["dfg"]
    assert set(dfg.keys()) >= {"nodes", "edges", "start_activities", "end_activities"}
    assert dfg["nodes"], "DFG should contain nodes for the activity sequence"


def test_progressive_recommendation_record_keeps_shape(monkeypatch, tmp_path) -> None:
    aid, entry, client = _seed(monkeypatch, tmp_path)

    _compute_to_end(client, aid)

    recs = entry["progressive_artifacts"]["method_recommendation"]["recommendations"]
    assert recs
    record = recs[0]
    for key in (
        "inferred_activity",
        "method",
        "execution_environment",
        "pattern_matched",
        "method_category",
        "confidence",
        "events",
    ):
        assert key in record
