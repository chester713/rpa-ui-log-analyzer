"""The layered map of an analysis, drawn by the ``/visualisation`` page.

The map is built from the rows of the exported analysis (Export CSV on the results page): one row for
every log event, and one for every implicit activity, inserted before the UI activity it precedes. The
same rows come from two sources. The stored analysis (``rows_from_view``) knows which attributes the
LLM identified as the application and the data context, and the rule-based segments. An exported CSV
file (``rows_from_export``) does not, so the context columns are taken from their names.
``build_model`` turns the rows into the layers the page draws, all aligned on one sequence: the
context, the context switches, the implicit activities, the UI activities, the log events, the
execution environment and the recommended methods.
"""

import csv
import io
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from src.models.event import recorded_value
from src.models.pattern import method_level

# What the export adds after the log's own columns, in order (see Export CSV on the results page).
EXPORT_COLUMNS = [
    "activity_no", "activity_type", "ui_activity", "pattern", "action", "object_type", "target",
    "execution_environment", "selected_method", "prioritised_methods", "method_note",
]

# What loggers usually call each role. Used only for an exported file, which does not say which
# attributes the LLM identified as the event name, the application and the data context.
_EVENT_COLUMNS = ("concept:name", "event", "activity", "event_name", "name", "action")
_SOFTWARE_COLUMNS = ("application", "app", "process", "process_name", "application_name")
_DATA_COLUMNS = ("browser_url", "url", "webpage", "workbook", "current_worksheet", "worksheet")

_VALUE_CHARS = 300  # a longer attribute value is cut in the model; the log keeps it whole
_LABEL_CHARS = 40
_SWITCH_NAME = re.compile(r"Switch context from (.+) to (.+)")
_IMPLICIT_TYPE = re.compile(r"implicit \((\w+)\)")


@lru_cache(maxsize=1)
def _categories() -> Dict[str, str]:
    """Pattern name (lower case) -> category (Extraction, Modification or Control)."""
    from src.matching import PATTERNS

    return {p.name.lower(): p.category for p in PATTERNS}


def _clip(value: Any, limit: int = _VALUE_CHARS) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _short(value: str) -> str:
    """A context value as a label: a URL without its scheme, query and trailing slash."""
    text = value.strip()
    if "://" in text:
        parsed = urlparse(text)
        shown = (parsed.netloc + parsed.path).rstrip("/")
        if shown:
            text = shown if parsed.scheme in ("http", "https") else f"{parsed.scheme}://{shown}"
    return _clip(text, _LABEL_CHARS)


# ── the rows of the export ───────────────────────────────────────────────────

def _activity(*, no, kind, rule, name, pattern, action, object_type, target, environment,
              methods, selected, note, **extra) -> Dict[str, Any]:
    """One activity as the map keeps it, from either source."""
    methods = [m for m in (methods or []) if m]
    if not methods and selected:
        methods = [selected]
    return {
        "no": no, "type": kind, "rule": rule, "name": name or "",
        "pattern": pattern or None, "action": action or None, "object_type": object_type or None,
        "target": target or None, "environment": environment or "unknown",
        "methods": [{"name": m, "level": method_level(m)} for m in methods],
        "selected": selected or None, "note": note or None, **extra,
    }


def rows_from_view(view: dict) -> dict:
    """The rows of the export, from a stored analysis (``progressive.build_view``).

    Implicit activities come immediately before the first event of the UI activity they precede, and
    those after the last one at the end, exactly as Export CSV writes them.
    """
    activities = view.get("activities") or []
    recorded_of_row = {r: a for a in activities if a["kind"] == "recorded" for r in a["rows"]}
    before: Dict[int, list] = {}
    pending: list = []
    for a in activities:
        if a["kind"] == "implicit":
            pending.append(a)
            continue
        if pending and a["rows"]:
            before[a["rows"][0]] = pending
        pending = []

    def convert(a: dict) -> Dict[str, Any]:
        return _activity(
            no=a["number"], kind=a["kind"], rule=a.get("rule"), name=a["name"], pattern=a.get("pattern"),
            action=a.get("action"), object_type=a.get("object_type"), target=a.get("target"),
            environment=a.get("environment"), methods=a.get("methods"), selected=a.get("method"),
            note=a.get("method_note"), index=a["index"],
            confidence=a.get("confidence"), reasoning=a.get("reasoning") or None,
            evidence=a.get("evidence") or [],
        )

    rows: List[Dict[str, Any]] = []
    for log_row in (view.get("log") or {}).get("rows") or []:
        for a in before.get(log_row["row_index"], []):
            rows.append({"row": None, "values": {}, "activity": convert(a)})
        a = recorded_of_row.get(log_row["row_index"])
        rows.append({"row": log_row["row_index"], "values": log_row["values"], "activity": convert(a) if a else None})
    for a in pending:
        rows.append({"row": None, "values": {}, "activity": convert(a)})

    roles = view.get("roles") or {}
    element = set(roles.get("element") or [])
    return {
        "columns": list((view.get("log") or {}).get("columns") or []),
        "event_column": roles.get("event_column"),
        "software": list(roles.get("application") or []),
        # An element identifier says which element, not which page or document.
        "data": [c for c in (roles.get("context") or []) if c not in element],
        "rows": rows,
        "segments": [
            {"label": f"S{i + 1}", "rows": s["rows"], "boundary": s.get("boundary")}
            for i, s in enumerate(view.get("segments") or [])
        ],
    }


def rows_from_export(text: str) -> dict:
    """The rows of an exported CSV file.

    Raises ValueError when the text is not an export: the first column must be ``row`` and the
    columns ``activity_no`` and ``activity_type`` must follow the log's own columns.
    """
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader, None) or []
    if not header or header[0] != "row" or "activity_no" not in header or "activity_type" not in header:
        raise ValueError(
            "This file is not an exported analysis: its first column must be 'row' and it must have the "
            "columns 'activity_no' and 'activity_type'. Use Export CSV on the results page."
        )
    start = header.index("activity_no")
    columns = header[1:start]

    rows: List[Dict[str, Any]] = []
    for fields in reader:
        if not any(f.strip() for f in fields):
            continue
        cell = {h: (fields[i] if i < len(fields) else "") for i, h in enumerate(header)}
        number = cell["row"].strip()
        activity = None
        no = cell["activity_no"].strip()
        if not number and not no:
            continue  # neither a log event nor an implicit activity
        if no:
            kind = cell["activity_type"].strip().lower()
            implicit = _IMPLICIT_TYPE.fullmatch(kind)
            methods = [m.strip() for m in cell.get("prioritised_methods", "").split(" > ")]
            activity = _activity(
                no=int(no) if no.isdigit() else no,
                kind="implicit" if implicit else "recorded",
                rule=implicit.group(1) if implicit else None,
                name=cell.get("ui_activity", ""), pattern=cell.get("pattern", "").strip(),
                action=cell.get("action", "").strip(), object_type=cell.get("object_type", "").strip(),
                target=cell.get("target", "").strip(),
                environment=cell.get("execution_environment", "").strip(),
                methods=methods, selected=cell.get("selected_method", "").strip(),
                note=cell.get("method_note", "").strip(),
            )
        rows.append({
            "row": int(number) if number.isdigit() else None,
            "values": {c: cell.get(c, "") for c in columns} if number else {},
            "activity": activity,
        })
    return {"columns": columns, "event_column": None, "software": None, "data": None, "rows": rows, "segments": []}


# ── the layers ───────────────────────────────────────────────────────────────

def _roles_from_names(columns: List[str]) -> Dict[str, Any]:
    """The event name, application and data-context columns, from the column names."""
    lowered = {c.lower(): c for c in columns}
    event = next((lowered[n] for n in _EVENT_COLUMNS if n in lowered), None) or (columns[0] if columns else None)
    return {
        "event": event,
        "software": [lowered[n] for n in _SOFTWARE_COLUMNS if n in lowered],
        "data": [lowered[n] for n in _DATA_COLUMNS if n in lowered],
    }


def _runs(keys: list) -> List[Dict[str, Any]]:
    """Maximal runs of equal, non-empty keys, as {"key", "from", "to"} over the slots."""
    runs: List[Dict[str, Any]] = []
    for i, key in enumerate(keys):
        if key is None:
            continue
        if runs and runs[-1]["key"] == key and runs[-1]["to"] == i - 1:
            runs[-1]["to"] = i
        else:
            runs.append({"key": key, "from": i, "to": i})
    return runs


def _context_per_slot(rows: list, software_columns: list, data_columns: list) -> tuple:
    """The software and data context of every slot.

    A value that was not recorded is no evidence of a change, so an event that records none
    continues the context before it. A new application starts a new segment, though, so the data
    context starts afresh there: a page or document of one application is not the context of another.
    An implicit activity has no values: it takes the context of the event it precedes (the activity it
    is inserted for), or of the last event when none follows.
    """
    def is_event(row: dict) -> bool:
        return row["row"] is not None or bool(row["values"])

    software: list = [None] * len(rows)
    data: list = [None] * len(rows)
    current_s = current_d = None
    for i, row in enumerate(rows):
        if not is_event(row):
            continue
        s = next((v for v in (recorded_value(row["values"].get(c)) for c in software_columns) if v is not None), None)
        shown = [_short(v) for v in (recorded_value(row["values"].get(c)) for c in data_columns) if v is not None]
        d = " · ".join(dict.fromkeys(shown[:2])) or None
        if s is not None and s != current_s:
            current_d = None
        current_s = s if s is not None else current_s
        current_d = d if d is not None else current_d
        software[i], data[i] = current_s, current_d

    following_s = following_d = None
    for i in range(len(rows) - 1, -1, -1):
        if is_event(rows[i]):
            following_s, following_d = software[i], data[i]
        else:
            software[i], data[i] = following_s, following_d
    last_s = last_d = None
    for i, row in enumerate(rows):
        if is_event(row):
            last_s, last_d = software[i], data[i]
        elif software[i] is None and data[i] is None:
            software[i], data[i] = last_s, last_d
    return software, data


def build_model(source: dict, title: str = "", aid: Optional[str] = None) -> dict:
    """The layers of the map, from the rows of an export (see ``rows_from_view`` and ``rows_from_export``).

    Every row is one slot of the sequence. Returns the slots, the activities (with the slots of their
    events), the context bands, the context switches, and the figures the page shows.
    """
    rows = source["rows"]
    named = _roles_from_names(source["columns"])
    event_column = source.get("event_column") or named["event"]
    software_columns = named["software"] if source.get("software") is None else source["software"]
    data_columns = named["data"] if source.get("data") is None else source["data"]
    categories = _categories()

    software, data = _context_per_slot(rows, software_columns, data_columns)

    slots: List[Dict[str, Any]] = []
    activities: Dict[Any, Dict[str, Any]] = {}
    for i, row in enumerate(rows):
        a = row["activity"]
        is_event = row["row"] is not None or bool(row["values"])
        if is_event:
            name = recorded_value(row["values"].get(event_column)) or ""
            attrs = {c: _clip(v) for c, v in row["values"].items() if recorded_value(v) is not None}
        else:
            name, attrs = (a or {}).get("name", ""), {}
        slots.append({
            "kind": "event" if is_event else "implicit", "row": row["row"], "name": name,
            "activity": a["no"] if a else None, "environment": (a or {}).get("environment") or "unknown",
            "software": software[i], "data": data[i], "attrs": attrs,
        })
        if a is None:
            continue
        if a["no"] not in activities:
            pattern = a["pattern"]
            activities[a["no"]] = {
                **a, "category": categories.get((pattern or "").lower()), "covered": pattern is not None,
                "from": i, "to": i, "events": [], "software": software[i], "data": data[i],
            }
        activity = activities[a["no"]]
        activity["to"] = i
        if is_event:
            activity["events"].append(i)

    switches = []
    for no, a in activities.items():
        if a["type"] != "implicit" or a["rule"] != "switch":
            continue
        slot = a["from"]
        match = _SWITCH_NAME.fullmatch(a["name"])
        before = next((software[j] for j in range(slot - 1, -1, -1) if slots[j]["kind"] == "event"), None)
        switches.append({
            "activity": no, "slot": slot,
            "from": match.group(1) if match else before, "to": match.group(2) if match else a["software"],
        })

    software_bands = [{"name": r["key"], "from": r["from"], "to": r["to"]} for r in _runs(software)]
    names = [b["name"] for b in software_bands]
    data_bands = [
        {"name": r["key"][1], "from": r["from"], "to": r["to"], "software": r["key"][0]}
        for r in _runs([(s, d) if d is not None else None for s, d in zip(software, data)])
    ]

    segments = []
    slot_of_row = {s["row"]: i for i, s in enumerate(slots) if s["row"] is not None}
    for segment in source.get("segments") or []:
        covered = [slot_of_row[r] for r in segment["rows"] if r in slot_of_row]
        if covered:
            segments.append({"label": segment["label"], "from": min(covered), "to": max(covered),
                             "boundary": segment.get("boundary")})

    recorded = [a for a in activities.values() if a["type"] == "recorded"]
    implicit = [a for a in activities.values() if a["type"] == "implicit"]
    return {
        "title": title, "aid": aid, "source": "analysis" if aid else "export",
        "roles": {"event_column": event_column, "software": software_columns, "data": data_columns,
                  "from_names": source.get("software") is None},
        "slots": slots, "activities": list(activities.values()),
        "bands": {"software": software_bands, "data": data_bands}, "software_names": list(dict.fromkeys(names)),
        "switches": switches, "segments": segments,
        "stats": {
            "events": sum(1 for s in slots if s["kind"] == "event"),
            "activities": len(recorded),
            "implicit": {rule: sum(1 for a in implicit if a["rule"] == rule) for rule in ("find", "focus", "switch")},
            "not_covered": sum(1 for a in recorded if not a["covered"]),
            "software_contexts": len(set(names)),
        },
    }
