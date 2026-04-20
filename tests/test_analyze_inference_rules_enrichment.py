"""Tests for analyze-time enrichment after inference rule overrides."""

from __future__ import annotations

from pathlib import Path

import app as webapp


class _FakeEvent:
    def __init__(self, row_index: int, attrs: dict):
        self.row_index = row_index
        self.event = "paste"
        self.attributes = attrs


class _FakeActivity:
    def __init__(self, name: str = "Write HTML element on webpage", confidence: float = 0.7):
        self.name = name
        self.confidence = confidence
        self.evidence = ["stub"]
        self.source_events = [0]


class _FakeMapping:
    def __init__(self, event: _FakeEvent):
        self.activity = _FakeActivity()
        self.events = [event]
        self.confidence = 0.7
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
        return []


class _FakeEventGrouper:
    pass


class _FakeMapper:
    def __init__(self, _grouper, _inferrer):
        pass

    def map(self, _events):
        attrs = {
            "application": "Chrome",
            "tag_name": "textfield",
            "element_id": "username",
            "webpage": "https://example.com/login",
        }
        return [_FakeMapping(_FakeEvent(0, attrs))]


def _patch_analysis_dependencies(monkeypatch, tmp_path: Path):
    uploads = tmp_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    monkeypatch.setitem(webapp.app.config, "UPLOAD_FOLDER", str(uploads))
    monkeypatch.setattr(webapp, "get_history", lambda: [])
    monkeypatch.setattr(webapp, "save_history", lambda _history: None)
    monkeypatch.setattr(
        webapp,
        "get_inference_rules",
        lambda: {
            "version": "1.0",
            "rules": [
                {
                    "enabled": True,
                    "match": {"any_event_keywords": ["paste"]},
                    "output": {
                        "web_activity_name": "Write HTML element on webpage",
                        "non_web_activity_name": "Write element",
                        "min_confidence": 0.8,
                    },
                }
            ],
        },
    )

    monkeypatch.setattr("src.llm.client.get_llm_client", lambda: object())
    monkeypatch.setattr("src.parser.csv_loader.CSVLoader", _FakeCSVLoader)
    monkeypatch.setattr("src.inference.event_grouper.EventGrouper", _FakeEventGrouper)
    monkeypatch.setattr("src.mapping.event_activity_mapper.EventActivityMapper", _FakeMapper)
    monkeypatch.setattr("src.matching.pattern_matcher.PatternMatcher", _FakePatternMatcher)
    monkeypatch.setattr("src.matching.pattern_matcher.get_context_from_events", lambda _events: "web")
    monkeypatch.setattr("src.matching.PATTERNS", [])
    monkeypatch.setattr("src.models.pattern.MethodRecommendation", _FakeRecommendation)
    monkeypatch.setattr(
        "src.process_mining.build_dfg_payload",
        lambda mappings, session_id: {
            "nodes": [m.activity.name for m in mappings],
            "edges": [],
            "start_activities": {},
            "end_activities": {},
        },
    )


def _prepare_uploaded_csv(client, tmp_path: Path):
    csv_path = tmp_path / "upload.csv"
    csv_path.write_text("Event,application\npaste,chrome\n", encoding="utf-8")
    with client.session_transaction() as sess:
        sess["uploaded_file"] = str(csv_path)
        sess["filename"] = "upload.csv"


def test_analyze_enriches_rule_overridden_generic_web_activity_name(monkeypatch, tmp_path: Path) -> None:
    _patch_analysis_dependencies(monkeypatch, tmp_path)
    client = webapp.app.test_client()
    _prepare_uploaded_csv(client, tmp_path)

    response = client.post("/analyze", json={"event_column": "Event"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["recommendations"][0]["inferred_activity"] == "Write textfield 'username' on example.com/login in Chrome"
