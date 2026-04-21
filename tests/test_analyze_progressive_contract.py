"""Contract tests for progressive artifact fields in analyze/history payloads."""

from __future__ import annotations

from pathlib import Path

import app as webapp


REQUIRED_STAGES = [
    "event_grouping",
    "activity_naming",
    "action_object_extraction",
    "pattern_matching",
    "context_determination",
    "method_recommendation",
]


class _FakeEvent:
    def __init__(self, row_index: int, event: str):
        self.row_index = row_index
        self.event = event
        self.attributes = {
            "application": "chrome",
            "tag_name": "button",
            "browser_url": "https://example.test",
        }


class _FakeActivity:
    def __init__(self, name: str, confidence: float = 0.9):
        self.name = name
        self.confidence = confidence
        self.evidence = ["stub"]
        self.source_events = [0]


class _FakeMapping:
    def __init__(self, name: str, row_index: int, event_name: str):
        self.activity = _FakeActivity(name)
        self.events = [_FakeEvent(row_index, event_name)]
        self.confidence = 0.9
        self.attribute_breakdown = {
            "context_switch": False,
            "previous_app": None,
            "current_app": None,
            "shared_attributes": ["application"],
            "attribute_counts": {"application": 1},
        }


class _FakePattern:
    category = "Extraction"

    def get_method_for_context(self, _context):
        return "DOM Parsing"


class _FakePatternMatcher:
    def __init__(self, _patterns):
        pass

    def match(self, _activity, _events, _context):
        return _FakePattern()

    def create_implicit_recommendations(self, _mappings, _context_sequence):
        return []


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


class _FakeCSVLoader:
    def __init__(self, _llm):
        self.detected_column = "Event"
        self._force_column = None

    def load(self, _filepath):
        return [_FakeEvent(0, "Open app"), _FakeEvent(1, "Click submit")]


class _FakeEventGrouper:
    pass


class _FakeActivityInferrer:
    def __init__(self, _llm):
        pass


class _FakeMapper:
    def __init__(self, _grouper, _inferrer):
        pass

    def map(self, _events):
        return [
            _FakeMapping("Open App", 0, "Open app"),
            _FakeMapping("Click Submit", 1, "Click submit"),
        ]


def _patch_analysis_dependencies(monkeypatch, tmp_path: Path):
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
    monkeypatch.setattr(
        "src.inference.activity_inferrer.ActivityInferrer", _FakeActivityInferrer
    )
    monkeypatch.setattr("src.mapping.event_activity_mapper.EventActivityMapper", _FakeMapper)
    monkeypatch.setattr("src.matching.pattern_matcher.PatternMatcher", _FakePatternMatcher)
    monkeypatch.setattr(
        "src.matching.pattern_matcher.get_context_from_events", lambda _events: "web"
    )
    monkeypatch.setattr("src.matching.PATTERNS", [])
    monkeypatch.setattr("src.models.pattern.MethodRecommendation", _FakeRecommendation)
    monkeypatch.setattr(
        "src.process_mining.build_dfg_payload",
        lambda mappings, session_id: {
            "nodes": ["Open App", "Click Submit"],
            "edges": [{"source": "Open App", "target": "Click Submit", "frequency": 1}],
            "start_activities": {"Open App": 1},
            "end_activities": {"Click Submit": 1},
        },
    )

    return saved


def _prepare_uploaded_csv(client, tmp_path: Path):
    csv_path = tmp_path / "upload.csv"
    csv_path.write_text("Event,application\nclick,chrome\nsubmit,chrome\n", encoding="utf-8")
    with client.session_transaction() as sess:
        sess["uploaded_file"] = str(csv_path)
        sess["filename"] = "upload.csv"


def test_analyze_adds_progressive_keys_without_breaking_existing_contract(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_analysis_dependencies(monkeypatch, tmp_path)
    client = webapp.app.test_client()
    _prepare_uploaded_csv(client, tmp_path)

    response = client.post("/analyze", json={"event_column": "Event"})
    payload = response.get_json()

    assert response.status_code == 200
    assert "activities" in payload
    assert "recommendations" in payload
    assert "history_id" in payload
    assert "dfg" in payload
    assert "progressive_artifacts" in payload
    assert "progressive_logic" in payload


def test_analyze_progressive_artifacts_expose_all_six_stages_in_fixed_order(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_analysis_dependencies(monkeypatch, tmp_path)
    client = webapp.app.test_client()
    _prepare_uploaded_csv(client, tmp_path)

    response = client.post("/analyze", json={"event_column": "Event"})
    payload = response.get_json()

    assert response.status_code == 200
    assert list(payload["progressive_artifacts"].keys()) == REQUIRED_STAGES
    assert list(payload["progressive_logic"].keys()) == REQUIRED_STAGES


def test_analyze_persists_progressive_artifacts_with_same_stage_keys(
    monkeypatch, tmp_path: Path
) -> None:
    saved = _patch_analysis_dependencies(monkeypatch, tmp_path)
    client = webapp.app.test_client()
    _prepare_uploaded_csv(client, tmp_path)

    response = client.post("/analyze", json={"event_column": "Event"})

    assert response.status_code == 200
    assert saved["history"] is not None
    persisted_entry = saved["history"][0]
    assert list(persisted_entry["progressive_artifacts"].keys()) == REQUIRED_STAGES
    assert list(persisted_entry["progressive_logic"].keys()) == REQUIRED_STAGES
