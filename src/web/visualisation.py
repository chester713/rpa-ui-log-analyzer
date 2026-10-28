"""The sequence graph of an analysis, drawn by the ``/visualisation`` page.

The graph is built from the rows of the exported analysis (Export CSV on the results page): one row for
every log event, and one for every implicit activity, inserted before the UI activity it precedes. The
same rows come from two sources. The stored analysis (``rows_from_view``) knows which attributes the
LLM identified as the application and the data context. An exported CSV file (``rows_from_export``)
does not, so the context columns are taken from their names.
``build_model`` turns the rows into the UI activities in the order of the log, one box each, with
everything the five layers of the page colour them by: where each came from (the log or a rule), its
pattern, its context, its execution environment and its recommended methods.
"""

import csv
import io
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from src.models.event import recorded_value
from src.models.pattern import level_name, method_family, method_level, why_method_applies

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
    return {"columns": columns, "event_column": None, "software": None, "data": None, "rows": rows}


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


def _methods(methods: list, environment: str) -> List[Dict[str, Any]]:
    """The prioritised methods of an activity, each with its family, level and why it applies."""
    return [
        {
            "name": m["name"], "family": method_family(m["name"]), "level": m["level"],
            "level_name": level_name(m["level"]) if m["level"] is not None else None,
            "why": why_method_applies(m["level"], environment) if m["level"] is not None else None,
        }
        for m in methods
    ]


def _selected_index(methods: list, selected: Optional[str]) -> Optional[int]:
    """The place of the selected method in the list: the first when none is named, None without methods."""
    if not methods:
        return None
    return next((i for i, m in enumerate(methods) if m["name"] == selected), 0)


def _graph_activity(a: dict, categories: Dict[str, str], software: Optional[str], data: Optional[str],
                    software_before: Optional[str]) -> Dict[str, Any]:
    """One box of the graph. Its events are added by ``build_model``."""
    methods = _methods(a["methods"], a["environment"])
    activity = {
        "no": a["no"], "index": a.get("index"), "name": a["name"],
        "origin": "recorded" if a["type"] == "recorded" else (a["rule"] or "implicit"),
        "pattern": a["pattern"], "category": categories.get((a["pattern"] or "").lower()),
        "action": a["action"], "object_type": a["object_type"], "target": a["target"],
        "environment": a["environment"], "software": software, "data": data,
        "methods": methods, "selected": _selected_index(methods, a["selected"]), "note": a["note"],
        "events": [],
    }
    for key in ("confidence", "reasoning", "evidence"):  # what the LLM said: a stored analysis only
        if key in a:
            activity[key] = a[key]
    if activity["origin"] == "switch":
        match = _SWITCH_NAME.fullmatch(a["name"])
        activity["switch"] = {"from": match.group(1) if match else software_before,
                              "to": match.group(2) if match else software}
    return activity


def build_model(source: dict, title: str = "", aid: Optional[str] = None) -> dict:
    """The sequence graph, from the rows of an export (see ``rows_from_view`` and ``rows_from_export``).

    Returns the UI activities in the order of the log, one entry each, the applications in order of
    appearance, and the figures the page shows. An activity keeps the log events it was made of.
    """
    rows = source["rows"]
    named = _roles_from_names(source["columns"])
    event_column = source.get("event_column") or named["event"]
    software_columns = named["software"] if source.get("software") is None else source["software"]
    data_columns = named["data"] if source.get("data") is None else source["data"]
    categories = _categories()

    software, data = _context_per_slot(rows, software_columns, data_columns)

    activities: Dict[Any, Dict[str, Any]] = {}
    events = without_activity = 0
    software_before: Optional[str] = None
    for i, row in enumerate(rows):
        a = row["activity"]
        is_event = row["row"] is not None or bool(row["values"])
        if a is not None and a["no"] not in activities:
            activities[a["no"]] = _graph_activity(a, categories, software[i], data[i], software_before)
        if not is_event:
            continue
        events += 1
        software_before = software[i] if software[i] is not None else software_before
        if a is None:
            without_activity += 1
            continue
        activities[a["no"]]["events"].append({
            "row": row["row"],
            "name": recorded_value(row["values"].get(event_column)) or "",
            "attrs": {c: _clip(v) for c, v in row["values"].items() if recorded_value(v) is not None},
        })

    listed = list(activities.values())
    recorded = [a for a in listed if a["origin"] == "recorded"]
    implicit = [a for a in listed if a["origin"] != "recorded"]
    names = list(dict.fromkeys(a["software"] for a in listed if a["software"]))
    return {
        "title": title, "aid": aid, "source": "analysis" if aid else "export",
        "roles": {"event_column": event_column, "software": software_columns, "data": data_columns,
                  "from_names": source.get("software") is None},
        "activities": listed, "software_names": names,
        "stats": {
            "events": events, "events_without_activity": without_activity,
            "activities": len(recorded),
            "implicit": {rule: sum(1 for a in implicit if a["origin"] == rule) for rule in ("find", "focus", "switch")},
            "not_covered": sum(1 for a in recorded if not a["pattern"]),
            "with_method": sum(1 for a in listed if a["methods"]),
            "software_contexts": len(names),
        },
    }
