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

    def __init__(self, llm_client=None, progress_callback=None, patterns=None):
        self.llm_client = llm_client
        self.progress_callback = progress_callback
        self.patterns = patterns or []

    def _extract_context_summary(self, events: List[Event]) -> Optional[Dict[str, str]]:
        """Extract a brief app/URL/window summary from a group's events for cross-group comparison."""
        context_keys = [
            "application", "app", "browser_url", "url", "webpage",
            "window_title", "window", "workbook",
        ]
        summary: Dict[str, str] = {}
        for key in context_keys:
            for e in events:
                val = e.attributes.get(key)
                if val and str(val).strip().lower() not in {"none", "null", ""}:
                    summary[key] = str(val).strip()
                    break
        return summary if summary else None

    def _build_pattern_reference(self) -> str:
        """Build a compact pattern reference block from loaded Pattern objects."""
        if not self.patterns:
            return (
                "RPA Patterns (choose exactly one name for the \"pattern\" field):\n"
                "Find Element, Read Element, Observe, Write Element, Delete Element, "
                "Disable Element, Open, Activate, Hover, Switch Context, Scroll, Focus, Refresh"
            )
        lines = ['RPA Pattern Reference (use exactly one pattern name for the "pattern" field):']
        for p in self.patterns:
            first_sentence = p.description.split(".")[0].strip() if p.description else ""
            lines.append(
                f"- {p.name} [Action={p.action}, Object={p.object}]: {first_sentence}"
            )
        return "\n".join(lines)

    def infer_activities(self, event_groups) -> List[Activity]:
        """
        Infer enriched activity list from event groups.

        For each event group produces (in order):
        - An implicit context-switch activity if the LLM detects an application change
        - An implicit prerequisite "Find <element>" activity if the LLM indicates one is needed
        - The main LLM-inferred activity

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

        # Precompute previous-group context summary for each group so the LLM can detect
        # context switches without relying on hardcoded attribute names.
        prev_summaries = [None] * len(normalised)
        for i in range(1, len(normalised)):
            prev_summaries[i] = self._extract_context_summary(normalised[i - 1].events)

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

        # Assemble activities in original group order.
        activities: List[Activity] = []
        for group_idx, group in enumerate(normalised):
            source_events = [e.row_index for e in group.events if e.row_index is not None]
            llm_result = llm_results.get(group_idx, {})

            # 1. Implicit context-switch activity — LLM-detected only
            cs_info = llm_result.get("context_switch") or {}
            if not isinstance(cs_info, dict):
                cs_info = {}
            llm_cs = cs_info.get("detected", False)
            from_ctx = cs_info.get("from_context") or None
            to_ctx = cs_info.get("to_context") or None

            if llm_cs and (from_ctx or to_ctx):
                activities.append(Activity(
                    name=f"Switch context from {from_ctx or 'unknown'} to {to_ctx or 'unknown'}",
                    confidence=1.0,
                    evidence=[],
                    source_events=source_events,
                    activity_type="context_switch",
                    is_implicit=True,
                    group_index=group_idx,
                    pattern_name="Switch Context",
                ))

            # 2. Prerequisite "Find <element>" activity — identified and named by LLM
            prereq = llm_result.get("prerequisite") or {}
            if prereq.get("needed") and prereq.get("name"):
                activities.append(Activity(
                    name=prereq["name"],
                    confidence=1.0,
                    evidence=[],
                    source_events=source_events,
                    activity_type="prerequisite",
                    is_implicit=True,
                    group_index=group_idx,
                    pattern_name=prereq.get("pattern", "Find Element"),
                ))

            # 3. Main activity
            activity_name = llm_result.get("activity_name")
            if not activity_name or not str(activity_name).strip():
                raise LLMError(
                    f"LLM did not return an activity name for group {group_idx}. "
                    "No fallback is applied — re-run once the LLM is available."
                )
            activities.append(Activity(
                name=activity_name,
                confidence=llm_result.get("confidence", 0.3),
                evidence=llm_result.get("evidence", []),
                reasoning=llm_result.get("reasoning", ""),
                source_events=source_events,
                activity_type="main",
                is_implicit=False,
                group_index=group_idx,
                pattern_name=llm_result.get("pattern"),
            ))

        return activities

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
                tag = (
                    e.attributes.get("tag_name")
                    or e.attributes.get("tag_type")
                    or e.attributes.get("element_id")
                )
                if tag:
                    parts.append(f"(element: {tag})")
                event_lines.append("- " + " ".join(parts))

            priority_keys = [
                "application", "app", "webpage", "url", "browser_url",
                "tag_name", "tag_type", "element_id", "id",
                "workbook", "worksheet", "cell_range", "cell_range_number", "window",
            ]
            attr_summary: Dict[str, set] = {}
            for e in events:
                for k, v in e.attributes.items():
                    if v and str(v).strip() and str(v).lower() not in {"none", "null"}:
                        attr_summary.setdefault(k, set()).add(str(v))

            attr_lines = []
            for k in priority_keys:
                if k in attr_summary:
                    vals = sorted(attr_summary[k])[:3]
                    attr_lines.append(f"  {k}: {', '.join(vals)}")

            if prev_ctx:
                prev_ctx_text = ", ".join(f"{k}={v}" for k, v in prev_ctx.items())
            else:
                prev_ctx_text = "(first activity — no previous context)"

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
        return f"""You are an RPA (Robotic Process Automation) designer analyzing UI event logs.

{pattern_reference}

Analyze the following {n} event group(s). Return a JSON ARRAY with exactly {n} objects — one per group, in the same order.

{groups_block}

For each group return this JSON structure:
{{
  "activity_name": "Verb + object in a UNIQUE, context-specific phrasing aligned with the matched pattern. Include the concrete detail that sets this interaction apart from similar ones — the specific field/element label, cell reference, value entered, URL, or page (e.g. 'Write \"John\" into First Name field', 'Activate Submit button on registration form', 'Read cell B2 from Forecast sheet')",
  "pattern": "Exactly one pattern name from the reference above — choose based on semantic meaning of the interaction, not the exact words in the log",
  "context_switch": {{"detected": false, "from_context": null, "to_context": null}},
  "prerequisite": {{"needed": false}},
  "evidence": ["2-4 concise observations from events/attributes"],
  "confidence": 0.9,
  "reasoning": "One sentence summary"
}}

Field guide:
- "context_switch": Set "detected" to true only when the user moves to a genuinely different application, tool, or execution environment compared to the "Previous context" shown above. A change in execution environment — web (browser/HTML), desktop (native application, spreadsheet), or screen (raw coordinates) — is always a context switch, as is moving between two different applications in the same environment. Examples that ARE context switches: Excel → Chrome, one web app → a different web app, desktop app → browser. Examples that are NOT: navigating to a new page within the same site, opening a modal in the same app, scrolling. When detected is true, "from_context" and "to_context" must name the environments (e.g. "Microsoft Excel", "Google Chrome").
- "prerequisite": Identify whether the bot must locate a specific UI element before performing the main action. Set "needed" to true whenever the activity reads from, writes to, focuses, or activates a specific element (input fields, buttons, dropdowns, checkboxes, links, table cells) — these element-targeting actions all require the element to be found first. Set "needed" to false for page-level actions that have no specific target element (opening a URL, scrolling, switching windows/context, refreshing, launching an application, passive observation). When needed is true, also provide "name" — the activity name for the Find step using the same UNIQUE, context-specific verb+object phrasing as "activity_name" above. Include the concrete detail that identifies the target — the specific field/element label, cell reference, sheet, page, or URL — so the Find name is never bare (e.g. "Find First Name field on registration form", "Find Submit button on registration form", "Find cell B2 in Forecast sheet"), and "pattern": always "Find Element".

CRITICAL OUTPUT RULES:
1. Return a valid JSON ARRAY with EXACTLY {n} object(s) — one per group, in the same order.
2. "activity_name" is MANDATORY in every object. Never omit it. If the events are ambiguous or repetitive, still provide a best-guess name using verb+object format (e.g. "Read cell value from spreadsheet", "Interact with page element").
3. Every "activity_name" MUST be UNIQUE across the array. When groups perform the same kind of action, tell them apart using concrete context from their own events/attributes — the specific field or element label, cell reference, value, URL, page, or step — so that no two names are identical (e.g. "Write \"John\" into First Name field" vs "Write \"Smith\" into Last Name field"; "Read cell A2 from Sheet1" vs "Read cell A3 from Sheet1"). Never disambiguate with bare counters like "(2)".
4. Output raw JSON only — no markdown fences, no explanation text before or after the array.

[{{"activity_name": "...", "pattern": "...", "context_switch": {{"detected": false, ...}}, "prerequisite": {{"needed": false}}, ...}}, ...]"""

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
