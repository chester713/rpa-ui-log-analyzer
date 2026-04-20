"""Tests for inferred-activity to DFG transformation."""

from src.models.activity import Activity, EventActivityMapping
from src.models.event import Event
from src.process_mining.dfg_builder import build_dfg_payload


def _mapping(activity_name: str, row_index: int) -> EventActivityMapping:
    activity = Activity(name=activity_name, confidence=0.9)
    event = Event(event=activity_name.lower(), attributes={}, row_index=row_index)
    return EventActivityMapping(
        activity=activity,
        events=[event],
        confidence=0.9,
        attribute_breakdown={},
    )


def _fake_discover_dfg(df, activity_key, timestamp_key, case_id_key):
    ordered = (
        df.sort_values([case_id_key, timestamp_key], kind="stable")[activity_key]
        .astype(str)
        .tolist()
    )
    dfg = {}
    for i in range(len(ordered) - 1):
        edge = (ordered[i], ordered[i + 1])
        dfg[edge] = dfg.get(edge, 0) + 1
    start = {ordered[0]: 1} if ordered else {}
    end = {ordered[-1]: 1} if ordered else {}
    return dfg, start, end


def test_build_dfg_payload_returns_expected_edges_for_ordered_session(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.process_mining.dfg_builder.discover_dfg",
        _fake_discover_dfg,
    )
    mappings = [
        _mapping("Open Browser", 0),
        _mapping("Search Product", 1),
        _mapping("Add To Cart", 2),
    ]

    payload = build_dfg_payload(mappings, session_id="session-1")

    assert payload["nodes"] == ["Open Browser", "Search Product", "Add To Cart"]
    assert payload["edges"] == [
        {"source": "Open Browser", "target": "Search Product", "frequency": 1},
        {"source": "Search Product", "target": "Add To Cart", "frequency": 1},
    ]


def test_build_dfg_payload_contains_start_and_end_activity_counts(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.process_mining.dfg_builder.discover_dfg",
        _fake_discover_dfg,
    )
    mappings = [
        _mapping("Login", 0),
        _mapping("Submit Form", 1),
        _mapping("Logout", 2),
    ]

    payload = build_dfg_payload(mappings, session_id="session-2")

    assert payload["start_activities"] == {"Login": 1}
    assert payload["end_activities"] == {"Logout": 1}


def test_build_dfg_payload_aggregates_repeated_adjacent_transitions(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.process_mining.dfg_builder.discover_dfg",
        _fake_discover_dfg,
    )
    mappings = [
        _mapping("Approve", 0),
        _mapping("Approve", 1),
        _mapping("Approve", 2),
    ]

    payload = build_dfg_payload(mappings, session_id="session-3")

    assert payload["nodes"] == ["Approve"]
    assert payload["edges"] == [
        {"source": "Approve", "target": "Approve", "frequency": 2}
    ]
    assert payload["start_activities"] == {"Approve": 1}
    assert payload["end_activities"] == {"Approve": 1}


def test_build_dfg_payload_uses_first_event_timestamp_for_order(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.process_mining.dfg_builder.discover_dfg",
        _fake_discover_dfg,
    )

    first = _mapping("Second Activity", 10)
    first.events[0].attributes["timestamp"] = "2026-04-20T10:00:05"

    second = _mapping("First Activity", 5)
    second.events[0].attributes["timestamp"] = "2026-04-20T10:00:01"

    payload = build_dfg_payload([first, second], session_id="session-ts")

    assert payload["edges"] == [
        {"source": "First Activity", "target": "Second Activity", "frequency": 1}
    ]
