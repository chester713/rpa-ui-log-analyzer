"""LLM-powered activity inference."""

import json
import logging
import re
from typing import List, Optional, Dict, Any
from ..models.event import Event
from ..models.activity import Activity

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
            activities.append(Activity(
                name=llm_result["activity_name"],
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
                "workbook", "worksheet", "window",
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
  "activity_name": "Verb + object naming the interaction's INTENT at a consistent semantic level, aligned with the matched pattern. Identify the activity by its stable target or role — the field's label, the button's purpose, the cell/column role — NOT by transient instance data such as the exact value typed, the row number, or a timestamp (e.g. 'Write First Name field', 'Activate Submit button', 'Read unit price cell'). Naming by stable role means genuinely different interactions get different names, while the same interaction performed again gets the same name.",
  "pattern": "Exactly one pattern name from the reference above — choose based on semantic meaning of the interaction, not the exact words in the log",
  "context_switch": {{"detected": false, "from_context": null, "to_context": null}},
  "prerequisite": {{"needed": false}},
  "evidence": ["2-4 concise observations from events/attributes"],
  "confidence": 0.9,
  "reasoning": "One sentence summary"
}}

Field guide:
- "context_switch": Set "detected" to true only when the user moves to a genuinely different application, tool, or execution environment compared to the "Previous context" shown above. A change in execution environment — web (browser/HTML), desktop (native application, spreadsheet), or screen (raw coordinates) — is always a context switch, as is moving between two different applications in the same environment. Examples that ARE context switches: Excel → Chrome, one web app → a different web app, desktop app → browser. Examples that are NOT: navigating to a new page within the same site, opening a modal in the same app, scrolling. When detected is true, "from_context" and "to_context" must name the environments (e.g. "Microsoft Excel", "Google Chrome").
- "prerequisite": Identify whether the bot must locate a specific UI element before performing the main action. Set "needed" to true whenever the activity reads from, writes to, focuses, or activates a specific element (input fields, buttons, dropdowns, checkboxes, links, table cells) — these element-targeting actions all require the element to be found first. Set "needed" to false for page-level actions that have no specific target element (opening a URL, scrolling, switching windows/context, refreshing, launching an application, passive observation). When needed is true, also provide "name" — the activity name for the Find step using the same verb+object format (e.g. "Find username field", "Find submit button", "Find country dropdown") — and "pattern": always "Find Element".

CRITICAL OUTPUT RULES:
1. Return a valid JSON ARRAY with EXACTLY {n} object(s) — one per group, in the same order.
2. "activity_name" is MANDATORY in every object. Never omit it. If the events are ambiguous or repetitive, still provide a best-guess name using verb+object format (e.g. "Read cell value from spreadsheet", "Interact with page element").
3. Name by SEMANTIC IDENTITY, not by occurrence:
   - Genuinely DIFFERENT interactions must get DIFFERENT names — distinguish them by their target/role (e.g. "Write First Name field" vs "Write Last Name field"), never by a counter.
   - The SAME interaction performed again must get the SAME name (e.g. the same button clicked repeatedly, or one step of a repeated cycle), so that real repetition is modelled as a loop in the process graph rather than a flat chain.
   - Do NOT inject transient details (the typed value, a row index, "(2)") just to force names apart — that would hide genuine loops.
4. Output raw JSON only — no markdown fences, no explanation text before or after the array.

[{{"activity_name": "...", "pattern": "...", "context_switch": {{"detected": false, ...}}, "prerequisite": {{"needed": false}}, ...}}, ...]"""

    def _parse_batch_response(self, raw: str, n: int) -> List[dict]:
        """Parse a JSON array response from a batch prompt. Returns exactly n dicts."""
        if not raw:
            return [{} for _ in range(n)]
        text = raw.strip()
        arr_match = re.search(r'\[.*\]', text, re.DOTALL)
        if arr_match:
            try:
                results = json.loads(arr_match.group())
                if isinstance(results, list):
                    while len(results) < n:
                        results.append({})
                    return results[:n]
            except json.JSONDecodeError:
                pass
        return [{} for _ in range(n)]

    def infer_activity(self, event_group: List[Event]) -> Activity:
        """Infer a single main activity (no implicit activities). Used for legacy callers."""
        if not event_group:
            return Activity(name="Empty", confidence=0.0, evidence=[], source_events=[])

        if self.llm_client is None:
            raise ValueError("LLM client required for activity inference")

        from ..inference.event_grouper import EventGroup
        group = EventGroup(events=event_group)
        prompt = self._build_prompt(group)
        raw = self.llm_client.complete(prompt)
        result = self._parse_response(raw)

        source_events = [e.row_index for e in event_group if e.row_index is not None]
        return Activity(
            name=result.get("activity_name", ""),
            confidence=result.get("confidence", 0.3),
            evidence=result.get("evidence", []),
            reasoning=result.get("reasoning", ""),
            source_events=source_events,
            pattern_name=result.get("pattern"),
        )

    def _build_prompt(self, group) -> str:
        """Build LLM prompt requesting a JSON response."""
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
            "workbook", "worksheet", "window",
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
                attr_lines.append(f"- {k}: {', '.join(vals)}")

        events_text = "\n".join(event_lines) or "- (none)"
        attrs_text = "\n".join(attr_lines) or "- (none available)"

        pattern_reference = self._build_pattern_reference()
        return f"""You are an RPA (Robotic Process Automation) designer analyzing UI event logs.

{pattern_reference}

Analyze the following UI events and return structured JSON for RPA design.

Events (temporal order):
{events_text}

Context attributes:
{attrs_text}

Instructions:
1. "activity_name": Name the interaction INTENT using verb + object format, aligned with the matched pattern vocabulary (e.g., "Write credentials into username field", "Activate submit button", "Open login page", "Read cell value from spreadsheet"). The verb should reflect the pattern's Action field.
2. "pattern": The single best-matching pattern name from the reference above. Choose based on the semantic meaning of the interaction — not the exact words in the log. A log may say "enterText", "inputValue", "keystroke" — all map to Write Element because they share the same intent.
3. "prerequisite": Identify whether the bot must locate a specific UI element before performing the main action. Set "needed" to true when the activity targets a specific element (input fields, buttons, dropdowns, checkboxes, links, table cells). Set "needed" to false for page-level actions (opening a URL, scrolling, switching windows, launching an application). When needed is true, also provide "name" — the activity name for the Find step using the same verb+object format (e.g. "Find username field", "Find submit button", "Find country dropdown") — and "pattern": always "Find Element".
4. "evidence": List of 2–4 concise observations drawn directly from the events and attributes above that justify your interpretation. Each item must name a specific event keyword or attribute value and explain what it signals.
5. "confidence": Your confidence from 0.0 to 1.0, reflecting how strongly the evidence supports your interpretation. Use lower values when events are ambiguous or key attributes are missing.
6. "reasoning": One sentence summarising your overall interpretation.

Respond with valid JSON only — no other text:
{{
  "activity_name": "...",
  "pattern": "Write Element",
  "prerequisite": {{"needed": true, "name": "Find username field", "pattern": "Find Element"}},
  "evidence": ["...", "..."],
  "confidence": 0.9,
  "reasoning": "..."
}}"""

    def _parse_response(self, response: str) -> dict:
        """Parse JSON response from LLM."""
        result: dict = {}
        if response:
            text = response.strip()
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
        return result
