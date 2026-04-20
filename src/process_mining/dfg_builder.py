"""Build deterministic DFG payloads from inferred activities."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from src.models.activity import EventActivityMapping

discover_dfg = None


class _MiniSeries:
    def __init__(self, values):
        self._values = list(values)

    def astype(self, _type):
        if _type is str:
            return _MiniSeries([str(v) for v in self._values])
        return self

    def tolist(self):
        return list(self._values)


class _MiniFrame:
    def __init__(self, rows):
        self._rows = list(rows)

    def sort_values(self, columns, kind="stable"):
        sorted_rows = sorted(
            self._rows,
            key=lambda row: tuple(row.get(col) for col in columns),
        )
        return _MiniFrame(sorted_rows)

    def __getitem__(self, key):
        return _MiniSeries([row.get(key) for row in self._rows])


def _sanitize_session_id(session_id: object) -> str:
    if session_id is None:
        return "session"
    return str(session_id)


def _sanitize_activity_name(name: object) -> str:
    if name is None:
        return ""
    return str(name)


def _to_activity_log(
    mappings: Iterable[EventActivityMapping], session_id: str
) -> object:
    rows = []
    base_time = datetime(2000, 1, 1)
    for idx, mapping in enumerate(mappings):
        rows.append(
            {
                "case:concept:name": session_id,
                "concept:name": _sanitize_activity_name(mapping.activity.name),
                "time:timestamp": base_time + timedelta(seconds=idx),
            }
        )

    try:
        import pandas as pd

        return pd.DataFrame(rows)
    except ModuleNotFoundError:
        return _MiniFrame(rows)


def build_dfg_payload(
    mappings: Iterable[EventActivityMapping], session_id: object
) -> dict:
    """Generate deterministic DFG payload from inferred activity mappings."""
    safe_session_id = _sanitize_session_id(session_id)
    mapping_list = list(mappings)

    if not mapping_list:
        return {
            "nodes": [],
            "edges": [],
            "start_activities": {},
            "end_activities": {},
        }

    log_df = _to_activity_log(mapping_list, safe_session_id)
    global discover_dfg
    if discover_dfg is None:
        from pm4py import discover_dfg as pm4py_discover_dfg

        discover_dfg = pm4py_discover_dfg

    dfg, start_activities, end_activities = discover_dfg(
        log_df,
        activity_key="concept:name",
        timestamp_key="time:timestamp",
        case_id_key="case:concept:name",
    )

    nodes = []
    seen_nodes = set()
    for mapping in mapping_list:
        node_name = _sanitize_activity_name(mapping.activity.name)
        if node_name not in seen_nodes:
            seen_nodes.add(node_name)
            nodes.append(node_name)
    edges = [
        {
            "source": _sanitize_activity_name(source),
            "target": _sanitize_activity_name(target),
            "frequency": int(frequency),
        }
        for (source, target), frequency in sorted(
            dfg.items(),
            key=lambda item: (
                _sanitize_activity_name(item[0][0]),
                _sanitize_activity_name(item[0][1]),
            ),
        )
    ]

    sorted_start = {
        _sanitize_activity_name(name): int(count)
        for name, count in sorted(
            start_activities.items(),
            key=lambda item: _sanitize_activity_name(item[0]),
        )
    }
    sorted_end = {
        _sanitize_activity_name(name): int(count)
        for name, count in sorted(
            end_activities.items(),
            key=lambda item: _sanitize_activity_name(item[0]),
        )
    }

    return {
        "nodes": nodes,
        "edges": edges,
        "start_activities": sorted_start,
        "end_activities": sorted_end,
    }
