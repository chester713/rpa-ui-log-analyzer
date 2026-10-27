"""LLM-powered activity inference."""

import json
import logging
import re
from typing import List, Optional, Dict, Any
from ..models.event import Event
from ..models.activity import Activity
from ..llm.client import LLMError

_logger = logging.getLogger(__name__)

_BATCH_SIZE = 5


class ActivityInferrer:
    """Uses LLM to infer activities from event groups."""

    _DEFAULT_APPLICATION_KEYS = ["application", "app"]
    _DEFAULT_CONTEXT_KEYS = ["browser_url", "url", "webpage", "window_title", "window", "workbook"]

    def __init__(
        self,
        llm_client=None,
        progress_callback=None,
        patterns=None,
        application_attributes: Optional[List[str]] = None,
        context_attributes: Optional[List[str]] = None,
        element_attributes: Optional[List[str]] = None,
    ):
        """
        Args:
            application_attributes: Columns that identify the active application, as
                identified by the LLM when the log was loaded (defaults to common names).
            context_attributes: Other columns that locate an event, e.g. URL or window.
            element_attributes: Columns that identify the target UI element (element id,
                XPath, cell reference, ...), used to tell whether activities share a target.
        """
        self.llm_client = llm_client
        self.progress_callback = progress_callback
        self.patterns = patterns or []
        self.application_attributes = list(application_attributes or self._DEFAULT_APPLICATION_KEYS)
        self.context_attributes = list(context_attributes or [])
        self.element_attributes = list(element_attributes or [])

    def _context_keys(self) -> List[str]:
        """Attributes compared between groups, application-related ones first."""
        keys: List[str] = []
        for key in (
            self.application_attributes + self._DEFAULT_APPLICATION_KEYS
            + self.context_attributes + self._DEFAULT_CONTEXT_KEYS
        ):
            if key not in keys:
                keys.append(key)
        return keys

    def _latest_context(self, events: List[Event]) -> Dict[str, str]:
        """The most recently recorded value of each application/URL/window attribute in a group."""
        latest: Dict[str, str] = {}
        for key in self._context_keys():
            for e in reversed(events):
                value = e.recorded(key)
                if value is not None:
                    latest[key] = value
                    break
        return latest

    def _build_pattern_reference(self) -> str:
        """Build a compact pattern reference block from loaded Pattern objects."""
        if not self.patterns:
            return (
                "RPA Patterns (choose one name for the \"pattern\" field, or null if none fits):\n"
                "Find Element, Read Element, Observe, Write Element, Delete Element, "
                "Disable Element, Open, Activate, Hover, Switch Context, Scroll, Focus, Refresh"
            )
        lines = ['RPA Pattern Reference (use one pattern name for the "pattern" field, or null if none fits):']
        for p in self.patterns:
            first_sentence = p.description.split(".")[0].strip() if p.description else ""
            lines.append(
                f"- {p.name} [Action={p.action}, Object={p.object}]: {first_sentence}"
            )
        return "\n".join(lines)

    def infer_activities(self, event_groups) -> List[Activity]:
        """
        Infer enriched activity list from event groups.

        The LLM names each group's UI activity, assigns its pattern (or none, when the
        collection has no fitting pattern) and names its target element. The implicit
        Switch context, Find and Focus activities are then inserted by fixed rules
        (see ``add_implicit_activities``), not by the LLM.

        Args:
            event_groups: List[EventGroup] or List[List[Event]] (legacy)

        Returns:
            Enriched List[Activity] — may be longer than the input groups.
        """
        from ..inference.event_grouper import EventGroup as EG

        normalised = []
        for g in event_groups:
            if isinstance(g, EG):
                normalised.append(g)
            else:
                normalised.append(EG(events=g))

        # Precompute the "previous context" for each group, shown to the LLM as
        # background when it names the activity. It is the most recently recorded value of each
        # application/URL/window attribute over ALL earlier groups, so a group that did
        # not record the application does not erase what is known about it. None marks
        # the first group; an empty dict means earlier groups recorded none of these.
        prev_summaries: List[Optional[Dict[str, str]]] = [None] * len(normalised)
        running: Dict[str, str] = {}
        for i, group in enumerate(normalised):
            if i > 0:
                prev_summaries[i] = dict(running)
            running.update(self._latest_context(group.events))

        # Process batches sequentially to stay within free-tier rate limits.
        indexed = [(i, g, prev_summaries[i]) for i, g in enumerate(normalised)]
        batches = [indexed[i:i + _BATCH_SIZE] for i in range(0, len(indexed), _BATCH_SIZE)]
        llm_results: Dict[int, dict] = {}
        completed = 0
        total = len(normalised)
        if self.progress_callback:
            self.progress_callback(0, total)
        for batch in batches:
            batch_results = self._call_llm_for_batch(batch)
            for group_idx, result in batch_results:
                llm_results[group_idx] = result
            completed += len(batch_results)
            if self.progress_callback:
                self.progress_callback(completed, total)

        # Main activities, in group order, exactly as the LLM named them.
        mains: List[Activity] = []
        for group_idx, group in enumerate(normalised):
            source_events = [e.row_index for e in group.events if e.row_index is not None]
            llm_result = llm_results.get(group_idx, {})
            activity_name = llm_result.get("activity_name")
            if not activity_name or not str(activity_name).strip():
                raise LLMError(
                    f"LLM did not return an activity name for group {group_idx}. "
                    "No fallback is applied — re-run once the LLM is available."
                )
            pattern = llm_result.get("pattern")
            if not isinstance(pattern, str) or not pattern.strip() or pattern.strip().lower() in ("null", "none"):
                pattern = None  # not covered by the pattern collection
            elif self.patterns:
                known = {p.name.lower(): p.name for p in self.patterns}
                if pattern.strip().lower() not in known:
                    raise LLMError(
                        f"LLM returned the pattern '{pattern}' for group {group_idx}, which is not in "
                        "the pattern collection. No fallback is applied — re-run the analysis."
                    )
                pattern = known[pattern.strip().lower()]
            target = llm_result.get("target")
            target = str(target).strip() if isinstance(target, str) and target.strip() else None
            context = llm_result.get("context")
            context = str(context).strip() if isinstance(context, str) and context.strip() else None
            mains.append(Activity(
                name=activity_name,
                confidence=llm_result.get("confidence", 0.3),
                evidence=llm_result.get("evidence", []),
                reasoning=llm_result.get("reasoning", ""),
                source_events=source_events,
                activity_type="main",
                is_implicit=False,
                group_index=group_idx,
                pattern_name=pattern,
                target=target,
                target_id=self._target_identity(group.events, target, context),
                context=context,
            ))

        return add_implicit_activities(normalised, mains, self.application_attributes)

    def _target_identity(
        self, events: List[Event], target: Optional[str], context: Optional[str] = None
    ) -> Optional[str]:
        """The identity of an activity's target, used to tell whether two activities act on
        the same element: the value of an element attribute recorded by any of its events,
        else (when the log records none) the target object and context named by the LLM."""
        for event in events:
            for key in self.element_attributes:
                value = event.recorded(key)
                if value is not None:
                    return f"{key}={value}"
        if not target:
            return None
        return " ".join(part for part in (target, context) if part).lower()

    def _call_llm_for_batch(self, indexed_groups: list) -> list:
        """Fan-out worker: one LLM call for a batch of groups. Returns [(group_idx, result_dict), ...]."""
        if self.llm_client is None:
            raise ValueError("LLM client required for activity inference")
        n = len(indexed_groups)
        prompt = self._build_batch_prompt(indexed_groups)
        raw = self.llm_client.complete(prompt)
        parsed = self._parse_batch_response(raw, n)
        return [(indexed_groups[i][0], parsed[i]) for i in range(n)]

    def _build_batch_prompt(self, indexed_groups: list) -> str:
        """Build a single prompt asking the LLM to analyse multiple event groups at once."""
        n = len(indexed_groups)
        sections = []
        for local_i, (_, group, prev_ctx) in enumerate(indexed_groups):
            events = group.events
            event_lines = []
            for e in events:
                parts = [e.event]
                tag = next(
                    (e.recorded(k) for k in self.element_attributes if e.recorded(k) is not None),
                    None,
                ) or (
                    e.attributes.get("tag_name")
                    or e.attributes.get("tag_type")
                    or e.attributes.get("element_id")
                )
                if tag:
                    parts.append(f"(element: {tag})")
                event_lines.append("- " + " ".join(parts))

            # The application, context and element attributes identified for this log
            # come first; common attribute names follow for logs where none were identified.
            priority_keys: List[str] = []
            for key in (
                self.application_attributes + self.context_attributes + self.element_attributes
                + self._DEFAULT_APPLICATION_KEYS + [
                    "webpage", "url", "browser_url",
                    "tag_name", "tag_type", "element_id", "id",
                    "workbook", "worksheet", "cell_range", "cell_range_number", "window",
                ]
            ):
                if key not in priority_keys:
                    priority_keys.append(key)
            attr_summary: Dict[str, set] = {}
            for e in events:
                for k in e.attributes:
                    v = e.recorded(k)
                    if v is not None:
                        attr_summary.setdefault(k, set()).add(v)

            attr_lines = []
            for k in priority_keys:
                if k in attr_summary:
                    vals = sorted(attr_summary[k])[:3]
                    attr_lines.append(f"  {k}: {', '.join(vals)}")

            if prev_ctx is None:
                prev_ctx_text = "(first activity — no previous context)"
            elif not prev_ctx:
                prev_ctx_text = "(no application, URL or window was recorded in earlier groups)"
            else:
                prev_ctx_text = ", ".join(f"{k}={v}" for k, v in prev_ctx.items())

            events_text = "\n".join(event_lines) or "- (none)"
            attrs_text = "\n".join(attr_lines) or "  (none available)"
            sections.append(
                f"GROUP {local_i + 1}:\n"
                f"Previous context: {prev_ctx_text}\n"
                f"Events:\n{events_text}\n"
                f"Context:\n{attrs_text}"
            )

        groups_block = "\n\n".join(sections)
        pattern_reference = self._build_pattern_reference()
        return f"""You are an RPA (Robotic Process Automation) designer analysing UI event logs.

{pattern_reference}

Analyze the following {n} event group(s). Return a JSON ARRAY with exactly {n} objects — one per group, in the same order.

{groups_block}

Each group is one UI activity: one action on one target. For each group return this JSON structure:
{{
  "activity_name": "Action + object + context: the action of the chosen pattern (e.g. Write, Read, Activate, Focus), or the recorded action if no pattern fits, followed by the target object and the context it resides in (e.g. 'Write First Name field on rpachallenge.com in Edge', 'Read cell A2 in Sheet 1 of challenge.xlsx in Excel', 'Activate Submit button on rpachallenge.com in Edge', 'Open rpachallenge.com in Edge'). Do not include input values such as the text that was typed or pasted.",
  "pattern": "One pattern name from the reference above, chosen by the semantic meaning of the interaction, not the exact words in the log (e.g. a click on a button activates it; a click on a text field focuses it). Use null if no pattern fits the interaction — never force a pattern.",
  "target": "The target object: the specific UI element the action is performed on, named by its label (e.g. 'First Name field', 'Submit button', 'cell A2'), or null for page- or application-level actions without a target element (opening a URL, scrolling a page, refreshing a page, switching application)",
  "context": "The context the target resides in, phrased to follow the object: the application and, within it, the webpage, window, workbook or worksheet (e.g. 'on rpachallenge.com in Edge', 'in Sheet 1 of challenge.xlsx in Excel')",
  "evidence": ["2-4 concise observations from events/attributes"],
  "confidence": 0.9,
  "reasoning": "One sentence summary"
}}

Implicit activities (locating an element first, focusing a field before writing, switching application) are added afterwards by fixed rules; do not describe them.

CRITICAL OUTPUT RULES:
1. Return a valid JSON ARRAY with EXACTLY {n} object(s) — one per group, in the same order.
2. "activity_name" is MANDATORY in every object. Never omit it. If the events are ambiguous, still name the activity by its recorded action, object and context.
3. Output raw JSON only — no markdown fences, no explanation text before or after the array.

[{{"activity_name": "...", "pattern": "...", "target": "...", "context": "...", "evidence": [...], "confidence": 0.9, "reasoning": "..."}}, ...]"""

    def _parse_batch_response(self, raw: str, n: int) -> List[dict]:
        """Parse a JSON array response from a batch prompt. Returns exactly n dicts.

        Raises LLMError if the response is missing, unparseable, or the wrong
        length. The pipeline has no fallback, so a malformed batch response is
        surfaced rather than silently padded with empty activities (which would
        yield false-positive results).
        """
        if not raw or not raw.strip():
            raise LLMError("LLM returned an empty response during activity naming.")
        text = raw.strip()
        arr_match = re.search(r'\[.*\]', text, re.DOTALL)
        if not arr_match:
            raise LLMError("LLM did not return a JSON array during activity naming.")
        try:
            results = json.loads(arr_match.group())
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM returned invalid JSON during activity naming: {exc}")
        if not isinstance(results, list):
            raise LLMError("LLM did not return a JSON array during activity naming.")
        if len(results) != n:
            raise LLMError(
                f"LLM returned {len(results)} activity result(s) but {n} were expected."
            )
        return results


# ── implicit activities (step 4 of the approach) ─────────────────────────────

# Find is required before every action that has a target element (step 4). These
# patterns always act on a target element...
ELEMENT_TARGETING_PATTERNS = {
    "read element", "observe", "write element", "delete element",
    "disable element", "activate", "focus", "hover",
}
# ...these act on a target element when they have one (scrolling a list or refreshing a
# control), but not when they act on a whole page or window.
ELEMENT_TARGETING_WHEN_NAMED = {"scroll", "refresh"}
# Open creates a new instance, Switch Context acts on a context and Find locates the
# element itself, so none of them is preceded by a Find.


def _acts_on_target_element(activity: Activity) -> bool:
    pattern = (activity.pattern_name or "").strip().lower()
    return pattern in ELEMENT_TARGETING_PATTERNS or (
        pattern in ELEMENT_TARGETING_WHEN_NAMED and bool(activity.target)
    )


def _implicit_name(action: str, activity: Activity) -> str:
    """Action + object + context for an implicit activity, from the activity it precedes."""
    parts = [action, activity.target or "the target element"]
    if activity.context:
        parts.append(activity.context)
    return " ".join(parts)


def _application_at(events: List[Event], attributes: List[str], last: bool) -> Optional[str]:
    """The first (or last) application recorded in a group, or None."""
    for event in (reversed(events) if last else events):
        for key in attributes:
            value = event.recorded(key)
            if value is not None:
                return value
    return None


def _check(rule: str, inserted: bool, reason: str) -> Dict[str, Any]:
    """What one implicit-activity rule decided for an activity, and why."""
    return {"rule": rule, "inserted": inserted, "reason": reason}


def _no_find_reason(activity: Activity) -> str:
    """Why an activity needs no Find: it does not act on a target element."""
    pattern = (activity.pattern_name or "").strip().lower()
    if not pattern:
        return "Not covered by the pattern collection, so it is not known to act on a target element."
    if pattern in ELEMENT_TARGETING_WHEN_NAMED:
        return (
            f"{activity.pattern_name} acts on the whole page or window here (no target element is "
            "named), so it needs no Find."
        )
    return f"{activity.pattern_name} does not act on a target element, so it needs no Find."


def add_implicit_activities(groups, mains: List[Activity], application_attributes: List[str]) -> List[Activity]:
    """Insert the implicit activities of step 4 before the activities that need them.

    Three rules are applied, in this order, to each main activity, each considering
    the sequence extended by the implicit activities already inserted:

    1. Switch context — the activity is recorded in a different application from the
       last application recorded before it (a missing value is no evidence, so the
       last recorded application is carried forward).
    2. Find element — the activity acts on a target element (see
       ``_acts_on_target_element``) and the preceding activity does not already
       target the same element.
    3. Focus — the activity writes into an element and the preceding activity does not
       focus that element.

    The result is: an element is found, then focused, then written to, with one Find
    serving both the Focus and the Write activity.

    What each rule decided for each main activity, and why, is kept on the main activity
    (``Activity.rule_checks``), whether or not the rule inserted anything.
    """
    enriched: List[Activity] = []
    last_app: Optional[str] = None

    for group, main in zip(groups, mains):
        events = group.events if hasattr(group, "events") else group
        source_events = main.source_events
        pattern = (main.pattern_name or "").strip().lower()
        checks: List[Dict[str, Any]] = []

        start_app = _application_at(events, application_attributes, last=False)
        if start_app is None:
            checks.append(_check(
                "switch", False,
                "No application is recorded for this UI activity; a missing value is no evidence of a switch.",
            ))
        elif last_app is None:
            checks.append(_check(
                "switch", False,
                f"{start_app} is the first application recorded in the log, so there is none to switch from.",
            ))
        elif start_app == last_app:
            checks.append(_check("switch", False, f"Recorded in {start_app}, the same application as before."))
        else:
            reason = (
                f"The activity is recorded in {start_app} and the preceding one in {last_app}, "
                "so the bot must switch its active application first."
            )
            checks.append(_check("switch", True, reason))
            enriched.append(Activity(
                name=f"Switch context from {last_app} to {start_app}",
                confidence=1.0,
                reasoning=reason,
                source_events=source_events,
                activity_type="context_switch",
                is_implicit=True,
                group_index=main.group_index,
                pattern_name="Switch Context",
            ))

        if not _acts_on_target_element(main):
            checks.append(_check("find", False, _no_find_reason(main)))
        else:
            previous = enriched[-1] if enriched else None
            if previous is not None and main.target_id and previous.target_id == main.target_id:
                checks.append(_check(
                    "find", False,
                    f"{main.pattern_name} acts on a target element, but the preceding activity "
                    f"({previous.name}) already targets it, so it is not located again.",
                ))
            else:
                reason = (
                    f"{main.pattern_name} acts on a target element that the preceding activity "
                    "does not target, so the bot must locate the element first."
                )
                checks.append(_check("find", True, reason))
                enriched.append(Activity(
                    name=_implicit_name("Find", main),
                    confidence=1.0,
                    reasoning=reason,
                    source_events=source_events,
                    activity_type="prerequisite",
                    is_implicit=True,
                    group_index=main.group_index,
                    pattern_name="Find Element",
                    target=main.target,
                    target_id=main.target_id,
                    context=main.context,
                ))

        if pattern != "write element":
            checks.append(_check("focus", False, "Only a Write needs its element focused for input."))
        else:
            previous = enriched[-1] if enriched else None
            focused = (
                previous is not None
                and (previous.pattern_name or "").strip().lower() == "focus"
                and main.target_id
                and previous.target_id == main.target_id
            )
            if focused:
                checks.append(_check(
                    "focus", False, f"The preceding activity ({previous.name}) already focuses the element.",
                ))
            else:
                reason = (
                    "Writing requires the target element to be focused for input, and the "
                    "preceding activity does not focus it."
                )
                checks.append(_check("focus", True, reason))
                enriched.append(Activity(
                    name=_implicit_name("Focus", main),
                    confidence=1.0,
                    reasoning=reason,
                    source_events=source_events,
                    activity_type="prerequisite",
                    is_implicit=True,
                    group_index=main.group_index,
                    pattern_name="Focus",
                    target=main.target,
                    target_id=main.target_id,
                    context=main.context,
                ))

        main.rule_checks = checks
        enriched.append(main)
        end_app = _application_at(events, application_attributes, last=True)
        if end_app is not None:
            last_app = end_app

    return enriched
