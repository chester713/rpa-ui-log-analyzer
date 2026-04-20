"""Contract tests for additive DFG fields in analyze/history payloads."""

from __future__ import annotations

from pathlib import Path

import app as webapp


class _FakeEvent:
    def __init__(self, row_index: int):
        self.row_index = row_index
        self.event = f"event-{row_index}"
        self.attributes = {"app": "Chrome"}


class _FakeActivity:
    def __init__(self, name: str, confidence: float = 0.9):
        self.name = name
        self.confidence = confidence
        self.evidence = ["stub"]
        self.source_events = [0]


class _FakeMapping:
    def __init__(self, name: str, row_index: int):
        self.activity = _FakeActivity(name)
        self.events = [_FakeEvent(row_index)]
        self.confidence = 0.9
        self.attribute_breakdown = {
            "context_switch": False,
            "previous_app": None,
            "current_app": None,
            "shared_attributes": [],
            "attribute_counts": {},
        }


class _FakeRecommendation:
    def __init__(self, **kwargs):
        self.data = kwargs
        self.method = kwargs.get("method")
        self.confidence = kwargs.get("confidence", 0.0)

    def to_dict(self):
        return {
            "inferred_activity": self.data.get("activity_name"),
            "activity_action": self.data.get("activity_action"),
            "activity_object": self.data.get("activity_object"),
            "events": self.data.get("events", []),
            "execution_environment": self.data.get("execution_environment"),
            "pattern_matched": None,
            "method": self.data.get("method"),
            "method_category": self.data.get("method_category"),
            "confidence": self.data.get("confidence"),
            "confidence_explanation": self.data.get("confidence_explanation"),
            "context_attributes_used": self.data.get("context_attributes_used", []),
            "context_switch": self.data.get("context_switch", False),
            "context_switch_from": self.data.get("context_switch_from"),
            "context_switch_to": self.data.get("context_switch_to"),
        }


class _FakePatternMatcher:
    def __init__(self, _patterns):
        pass

    def match(self, _activity, _events, _context):
        return None

    def create_implicit_recommendations(self, _mappings, _context_sequence):
        return []


class _FakeCSVLoader:
    def __init__(self, _llm):
        self.detected_column = "Event"
        self._force_column = None

    def load(self, _filepath):
        return [_FakeEvent(0), _FakeEvent(1)]


class _FakeEventGrouper:
    pass


class _FakeActivityInferrer:
    def __init__(self, _llm):
        pass


class _FakeMapper:
    def __init__(self, _grouper, _inferrer):
        pass

    def map(self, _events):
        return [_FakeMapping("Open App", 0), _FakeMapping("Click Button", 1)]


def _patch_analysis_dependencies(monkeypatch, tmp_path: Path, fake_dfg: dict):
    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    monkeypatch.setitem(webapp.app.config, "UPLOAD_FOLDER", str(uploads))
    monkeypatch.setattr(webapp, "get_history", lambda: [])

    saved = {"history": None}

    def _save_history(history):
        saved["history"] = history

    monkeypatch.setattr(webapp, "save_history", _save_history)
    monkeypatch.setattr(webapp, "get_inference_rules", lambda: {"rules": []})
    monkeypatch.setattr(webapp, "MAX_HISTORY_ENTRIES", 5)

    monkeypatch.setattr("src.llm.client.get_llm_client", lambda: object())
    monkeypatch.setattr("src.parser.csv_loader.CSVLoader", _FakeCSVLoader)
    monkeypatch.setattr("src.inference.event_grouper.EventGrouper", _FakeEventGrouper)
    monkeypatch.setattr("src.inference.activity_inferrer.ActivityInferrer", _FakeActivityInferrer)
    monkeypatch.setattr("src.mapping.event_activity_mapper.EventActivityMapper", _FakeMapper)
    monkeypatch.setattr("src.matching.pattern_matcher.PatternMatcher", _FakePatternMatcher)
    monkeypatch.setattr("src.matching.pattern_matcher.get_context_from_events", lambda _events: "web")
    monkeypatch.setattr("src.matching.PATTERNS", [])
    monkeypatch.setattr("src.models.pattern.MethodRecommendation", _FakeRecommendation)
    monkeypatch.setattr("src.process_mining.dfg_builder.build_dfg_payload", lambda mappings, session_id: fake_dfg)

    return saved


def _prepare_uploaded_csv(client, tmp_path: Path):
    csv_path = tmp_path / "upload.csv"
    csv_path.write_text("Event,application\nclick,chrome\nsubmit,chrome\n", encoding="utf-8")
    with client.session_transaction() as sess:
        sess["uploaded_file"] = str(csv_path)
        sess["filename"] = "upload.csv"


def test_analyze_adds_dfg_without_breaking_existing_keys(monkeypatch, tmp_path: Path) -> None:
    fake_dfg = {
        "nodes": ["Open App", "Click Button"],
        "edges": [{"source": "Open App", "target": "Click Button", "frequency": 1}],
        "start_activities": {"Open App": 1},
        "end_activities": {"Click Button": 1},
    }
    _patch_analysis_dependencies(monkeypatch, tmp_path, fake_dfg)

    client = webapp.app.test_client()
    _prepare_uploaded_csv(client, tmp_path)

    response = client.post("/analyze", json={"event_column": "Event"})
    payload = response.get_json()

    assert response.status_code == 200
    assert "activities" in payload
    assert "recommendations" in payload
    assert "history_id" in payload
    assert payload["dfg"] == fake_dfg


def test_analyze_persists_dfg_in_history_entry(monkeypatch, tmp_path: Path) -> None:
    fake_dfg = {
        "nodes": ["A", "B"],
        "edges": [{"source": "A", "target": "B", "frequency": 2}],
        "start_activities": {"A": 1},
        "end_activities": {"B": 1},
    }
    saved = _patch_analysis_dependencies(monkeypatch, tmp_path, fake_dfg)

    client = webapp.app.test_client()
    _prepare_uploaded_csv(client, tmp_path)

    response = client.post("/analyze", json={"event_column": "Event"})

    assert response.status_code == 200
    assert saved["history"] is not None
    assert saved["history"][0]["dfg"] == fake_dfg


def test_analyze_keeps_recommendation_record_shape(monkeypatch, tmp_path: Path) -> None:
    _patch_analysis_dependencies(
        monkeypatch,
        tmp_path,
        {
            "nodes": [],
            "edges": [],
            "start_activities": {},
            "end_activities": {},
        },
    )

    client = webapp.app.test_client()
    _prepare_uploaded_csv(client, tmp_path)

    response = client.post("/analyze", json={"event_column": "Event"})
    payload = response.get_json()

    assert response.status_code == 200
    recommendation = payload["recommendations"][0]
    assert set(recommendation.keys()) == {
        "inferred_activity",
        "activity_action",
        "activity_object",
        "events",
        "execution_environment",
        "pattern_matched",
        "method",
        "method_category",
        "confidence",
        "confidence_explanation",
        "context_attributes_used",
        "context_switch",
        "context_switch_from",
        "context_switch_to",
    }
