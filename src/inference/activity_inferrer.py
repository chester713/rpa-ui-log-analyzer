"""LLM-powered activity inference."""

import json
import logging
import os
import re
from urllib.parse import urlparse
from typing import List, Optional, Dict, Any
from ..models.event import Event
from ..models.activity import Activity

_logger = logging.getLogger(__name__)


class ActivityInferrer:
    """Uses LLM to infer activities from event groups."""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def infer_activities(self, event_groups) -> List[Activity]:
        """
        Infer enriched activity list from event groups.

        For each event group produces (in order):
        - An implicit context-switch activity if the application changed
        - An implicit prerequisite "Find <element>" activity if the main
          activity targets a specific UI element
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

        activities: List[Activity] = []

        for group_idx, group in enumerate(normalised):
            source_events = [e.row_index for e in group.events if e.row_index is not None]

            # 1. Implicit context-switch activity (no LLM needed)
            if group.is_context_switch and group.previous_app and group.current_app:
                activities.append(Activity(
                    name=f"Switch context from {group.previous_app} to {group.current_app}",
                    confidence=1.0,
                    evidence=[],
                    source_events=source_events,
                    activity_type="context_switch",
                    is_implicit=True,
                    group_index=group_idx,
                ))

            # 2. LLM call for main activity interpretation
            if self.llm_client is None:
                llm_result = self._mock_infer_result(group.events)
            else:
                prompt = self._build_prompt(group)
                try:
                    raw = self.llm_client.complete(prompt)
                    llm_result = self._parse_response(raw)
                except Exception as exc:
                    _logger.warning("LLM inference failed for group %d: %s", group_idx, exc)
                    llm_result = {}

            # When LLM is unavailable or returns an incomplete response, fill gaps
            # with rule-based detection so prerequisite activities are still generated.
            if not llm_result.get("activity_name") or "requires_find" not in llm_result:
                fallback = self._mock_infer_result(group.events)
                if not llm_result.get("activity_name"):
                    llm_result["activity_name"] = fallback["activity_name"]
                if "requires_find" not in llm_result:
                    llm_result["requires_find"] = fallback.get("requires_find", False)
                    if fallback.get("find_target"):
                        llm_result.setdefault("find_target", fallback["find_target"])

            # 3. Implicit prerequisite "Find <element>" activity
            if llm_result.get("requires_find") and llm_result.get("find_target"):
                activities.append(Activity(
                    name=f"Find {llm_result['find_target']}",
                    confidence=1.0,
                    evidence=[],
                    source_events=source_events,
                    activity_type="prerequisite",
                    is_implicit=True,
                    group_index=group_idx,
                ))

            # 4. Main activity
            activities.append(Activity(
                name=llm_result["activity_name"],
                confidence=llm_result.get("confidence", 0.3),
                evidence=llm_result.get("evidence", []),
                reasoning=llm_result.get("reasoning", ""),
                source_events=source_events,
                activity_type="main",
                is_implicit=False,
                group_index=group_idx,
            ))

        return activities

    def infer_activity(self, event_group: List[Event]) -> Activity:
        """Infer a single main activity (no implicit activities). Used for legacy callers."""
        if not event_group:
            return Activity(name="Empty", confidence=0.0, evidence=[], source_events=[])

        if self.llm_client is None:
            return self._mock_infer(event_group)

        from ..inference.event_grouper import EventGroup
        group = EventGroup(events=event_group)
        prompt = self._build_prompt(group)
        try:
            raw = self.llm_client.complete(prompt)
            result = self._parse_response(raw)
        except Exception as exc:
            _logger.warning("LLM inference failed in infer_activity: %s", exc)
            result = {}

        name = result.get("activity_name") or self._derive_fallback_activity_name(event_group)
        source_events = [e.row_index for e in event_group if e.row_index is not None]

        return Activity(
            name=name,
            confidence=result.get("confidence", 0.3),
            evidence=result.get("evidence", []),
            reasoning=result.get("reasoning", ""),
            source_events=source_events,
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

        return f"""You are an RPA (Robotic Process Automation) designer analyzing UI event logs.

Analyze the following UI events and return structured JSON for RPA design.

Events (temporal order):
{events_text}

Context attributes:
{attrs_text}

Instructions:
1. "activity_name": Natural language name capturing the INTERACTION INTENT, not the low-level events. Use verb + object format (e.g., "Write data into search field", "Click submit button", "Select option from dropdown", "Read cell value from spreadsheet").
2. "requires_find": In RPA the bot must LOCATE a UI element before interacting with it. Set true when this activity targets a specific element (input fields, buttons, dropdowns, checkboxes, links, table cells). Set false for page-level actions (opening a URL, scrolling, switching windows, launching an application).
3. "find_target": If requires_find is true, concisely describe the element to locate (e.g., "username textfield", "login button", "country dropdown"). Omit if requires_find is false.
4. "evidence": List of 2–4 concise observations drawn directly from the events and attributes above that justify your interpretation. Each item must name a specific event keyword or attribute value and explain what it signals. Example: ["Event 'type' on input element indicates keyboard text entry", "browser_url 'checkout.store.com' places action in e-commerce checkout context", "Element tag 'button' with id 'submit' identifies the target element"].
5. "confidence": Your confidence from 0.0 to 1.0, reflecting how strongly the evidence supports your interpretation. Use lower values when events are ambiguous or key attributes are missing.
6. "reasoning": One sentence summarising your overall interpretation.

Respond with valid JSON only — no other text:
{{
  "activity_name": "...",
  "requires_find": true,
  "find_target": "...",
  "evidence": ["...", "..."],
  "confidence": 0.9,
  "reasoning": "..."
}}"""

    def _parse_response(self, response: str, events=None):
        """Parse JSON response from LLM with line-based text fallback.

        When ``events`` is provided, returns an Activity, applying an
        event-derived fallback name whenever the parsed name is too generic.
        When ``events`` is None, returns a plain dict (existing internal API).
        """
        result: dict = {}

        if response:
            text = response.strip()

            # Extract JSON object — handle markdown code fences too
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

            if not result:
                # Fallback: line-based parsing for non-JSON responses
                for line in text.splitlines():
                    lower = line.lower().strip()
                    if lower.startswith("activity:") or lower.startswith("activity name:"):
                        result["activity_name"] = re.sub(
                            r"^activity( name)?:", "", line, flags=re.IGNORECASE
                        ).strip()
                    elif lower.startswith("confidence:"):
                        try:
                            result["confidence"] = float(
                                re.sub(r"^confidence:", "", line, flags=re.IGNORECASE).strip()
                            )
                        except ValueError:
                            pass

        if events is None:
            return result

        # With events: check if name is generic and derive a better one if so
        name = result.get("activity_name", "")
        if not name or self._is_generic_activity_name(name):
            name = self._derive_fallback_activity_name(list(events))

        source_events = [e.row_index for e in events if e.row_index is not None]
        return Activity(
            name=name,
            confidence=result.get("confidence", 0.3),
            evidence=result.get("evidence", []),
            reasoning=result.get("reasoning", ""),
            source_events=source_events,
        )

    def _is_generic_activity_name(self, name: str) -> bool:
        """Return True when a name is too generic to be useful."""
        text = str(name).strip().lower()
        return any(p in text for p in ("unknown activity", "html element", "perform ui interaction"))

    def _post_process_inferred_name(self, name: str, events) -> str:
        """Replace a generic activity name with one derived from event attributes."""
        if not events or not name:
            return name
        if not self._is_generic_activity_name(name):
            return name
        return self._derive_fallback_activity_name(list(events))

    def _derive_fallback_activity_name(self, event_group: List[Event]) -> str:
        """Derive a meaningful fallback name when the LLM returns nothing."""
        if not event_group:
            return "Perform UI interaction"
        action, target, context = self._derive_activity_components(event_group)
        return self._compose_activity_name(action, target, context)

    def _derive_activity_components(
        self, event_group: List[Event]
    ) -> tuple:
        """Infer action/target/context from grouped events and attributes (fallback only)."""
        if not event_group:
            return "Perform", "interaction", None

        event_text = " ".join([e.event.lower() for e in event_group])
        attrs = self._collect_attributes(event_group)

        if any(w in event_text for w in ["open", "newworkbook", "openworkbook", "openwindow", "launch"]):
            action = "Open"
        elif any(w in event_text for w in ["paste", "type", "input", "changefield", "write", "fill", "enter"]):
            action = "Write"
        elif any(w in event_text for w in ["click", "activate", "press", "tap"]):
            action = "Click"
        elif any(w in event_text for w in ["getcell", "read", "extract"]):
            action = "Read"
        elif any(w in event_text for w in ["select", "tab", "navigate", "startpage", "link"]):
            action = "Navigate"
        else:
            action = "Perform"

        if self._is_web_group(event_group):
            target, context = self._build_web_target_context(attrs, event_group)
        else:
            target, context = self._build_desktop_target_context(attrs)

        return action, target, context

    def _compose_activity_name(self, action: str, target: str, context: Optional[str]) -> str:
        core = f"{(action or 'Perform').strip()} {(target or 'interaction').strip()}".strip()
        if context:
            return f"{core} {context}".strip()
        return core

    def _collect_attributes(self, event_group: List[Event]) -> Dict[str, Any]:
        key_order = [
            "element_id", "id", "tag_name", "tag_type", "xpath", "xpath_full",
            "browser_url", "url", "webpage", "application", "app",
            "workbook", "worksheet", "current_worksheet",
            "cell_range", "cell_range_number", "event_src_path",
        ]
        out: Dict[str, Any] = {}
        for key in key_order:
            value = self._first_present_value(event_group, key)
            if value is not None:
                out[key] = value
        return out

    def _first_present_value(self, event_group: List[Event], key: str) -> Optional[str]:
        for event in event_group:
            value = (event.attributes or {}).get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text and text.lower() not in {"none", "null"}:
                return text
        return None

    def _is_web_group(self, event_group: List[Event]) -> bool:
        return any(
            (e.attributes.get("browser_url") or e.attributes.get("url") or e.attributes.get("webpage"))
            or str(e.attributes.get("application", "")).lower() in ["edge", "chrome", "firefox", "safari"]
            or str(e.attributes.get("category", "")).lower() == "browser"
            for e in event_group
        )

    def _build_web_target_context(
        self, attrs: Dict[str, Any], event_group: List[Event]
    ) -> tuple:
        tag = self._humanize_token(
            attrs.get("tag_name") or attrs.get("tag_type") or attrs.get("element_type") or "element"
        )
        element_id = attrs.get("element_id") or attrs.get("id")
        xpath = attrs.get("xpath") or attrs.get("xpath_full")
        url = attrs.get("browser_url") or attrs.get("url") or attrs.get("webpage")

        if element_id and not self._is_opaque_identifier(element_id):
            target = f"{tag} '{element_id}'"
        else:
            locator_hint = self._build_web_locator_hint(xpath, event_group)
            if xpath and not self._is_opaque_identifier(xpath):
                xpath_hint = self._humanize_xpath(xpath)
                target = (
                    f"{tag} {xpath_hint}"
                    if not locator_hint
                    else f"{tag} {xpath_hint} ({locator_hint})"
                )
            elif locator_hint:
                target = f"{tag} element ({locator_hint})"
            else:
                target = f"{tag} element"

        page_hint = self._build_webpage_hint(url)
        context_parts = [f"on {page_hint}" if page_hint else "on webpage"]
        app = attrs.get("application") or attrs.get("app")
        if app:
            context_parts.append(f"in {self._humanize_token(app)}")

        return target, " ".join(context_parts)

    def _build_web_locator_hint(self, xpath: Optional[str], event_group: List[Event]) -> Optional[str]:
        parts: List[str] = []
        if xpath and not self._is_opaque_identifier(xpath):
            xpath_tip = self._humanize_xpath(xpath).strip("'")
            if xpath_tip and xpath_tip != "element":
                parts.append(xpath_tip)
            xpath_row = self._extract_xpath_row_context(xpath)
            if xpath_row:
                parts.append(xpath_row)
        if not parts:
            row_hint = self._derive_row_index_hint(event_group)
            if row_hint:
                parts.append(row_hint)
        return ", ".join(parts[:2]) if parts else None

    def _build_desktop_target_context(self, attrs: Dict[str, Any]) -> tuple:
        app = attrs.get("application") or attrs.get("app")
        workbook = attrs.get("workbook")
        worksheet = attrs.get("worksheet") or attrs.get("current_worksheet")
        cell_range = attrs.get("cell_range") or attrs.get("cell_range_number")
        src_path = attrs.get("event_src_path")

        if cell_range:
            target = f"cell range {cell_range}"
        elif worksheet:
            target = f"worksheet {worksheet}"
        elif workbook:
            target = f"workbook {self._basename(workbook)}"
        elif src_path:
            target = f"file {self._basename(src_path)}"
        elif app:
            target = f"{self._humanize_token(app)} window"
        else:
            target = "element"

        context_parts = []
        if app:
            context_parts.append(self._humanize_token(app))
        if workbook:
            context_parts.append(f"workbook {self._basename(workbook)}")
        if worksheet:
            context_parts.append(f"sheet {worksheet}")

        context = f"in {' / '.join(context_parts)}" if context_parts else "in application"
        return target, context

    def _extract_domain(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        text = str(url).strip()
        if not text:
            return None
        if "://" not in text:
            text = f"https://{text}"
        parsed = urlparse(text)
        host = (parsed.hostname or "").strip().lower()
        return host or None

    def _build_webpage_hint(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        text = str(url).strip()
        if not text:
            return None
        if "://" not in text:
            text = f"https://{text}"
        parsed = urlparse(text)
        domain = (parsed.hostname or "").strip().lower()
        if not domain:
            return None
        path = (parsed.path or "").strip().rstrip("/")
        return f"{domain}{path}" if path and path != "/" else domain

    def _humanize_xpath(self, xpath: str) -> str:
        parts = [p for p in str(xpath).split("/") if p and p not in {"html", "body"}]
        if not parts:
            return "element"
        tip = parts[-1]
        tag_match = re.match(r"^([a-zA-Z][a-zA-Z0-9_\-]*)", tip)
        tag = (tag_match.group(1) if tag_match else "element").lower()
        preferred_attr = None
        for attr in ["aria-label", "name", "type", "title", "placeholder", "value"]:
            attr_match = re.search(rf"@{re.escape(attr)}=['\"]([^'\"]+)['\"]", tip)
            if attr_match:
                preferred_attr = f"{attr}={attr_match.group(1)}"
                break
        idx_match = re.search(r"\[(\d+)\](?!.*\[\d+\])", tip)
        index = idx_match.group(1) if idx_match else None
        parts_out = [tag]
        if preferred_attr:
            parts_out.append(preferred_attr)
        if index:
            parts_out.append(f"#{index}")
        return f"'{' '.join(parts_out)}'"

    def _extract_xpath_row_context(self, xpath: str) -> Optional[str]:
        row_match = re.search(r"/(?:tr|li)\[(\d+)\]", str(xpath), flags=re.IGNORECASE)
        return f"row {row_match.group(1)}" if row_match else None

    def _derive_row_index_hint(self, event_group: List[Event]) -> Optional[str]:
        for event in event_group:
            if event.row_index is not None:
                return f"event row {event.row_index}"
        return None

    def _basename(self, path_value: str) -> str:
        text = str(path_value).strip().rstrip("\\/")
        return os.path.basename(text) or text

    def _humanize_token(self, value: str) -> str:
        text = str(value).strip()
        if not text:
            return "element"
        return re.sub(r"\s+", " ", text.replace("_", " ").replace("-", " "))

    def _is_opaque_identifier(self, value: str) -> bool:
        text = str(value).strip()
        if not text:
            return True
        if any(token in text for token in ["/", "[", "]", "@", "="]):
            return False
        if len(text) >= 32 and " " not in text:
            return True
        if re.fullmatch(r"[0-9a-fA-F\-]{24,}", text):
            return True
        # Chrome extension IDs: 32-char lowercase a-p strings
        if re.fullmatch(r"[a-p]{32}", text):
            return True
        return False

    def _mock_infer_result(self, event_group: List[Event]) -> dict:
        """Rule-based fallback result when no LLM client is configured."""
        event_text = " ".join([e.event.lower() for e in event_group])
        action, target, context = self._derive_activity_components(event_group)
        name = self._compose_activity_name(action, target, context)

        requires_find = any(
            w in event_text
            for w in ["click", "type", "fill", "input", "paste", "changefield", "select", "read", "getcell"]
        )
        find_target = target if requires_find else None

        evidence = []
        input_kws = ["type", "fill", "input", "paste", "changefield"]
        click_kws = ["click", "select", "press"]
        read_kws = ["getcell", "read", "extract"]
        nav_kws = ["navigate", "tab", "startpage", "link"]
        open_kws = ["open", "newworkbook", "openworkbook", "openwindow", "launch"]

        matched_input = next((w for w in input_kws if w in event_text), None)
        matched_click = next((w for w in click_kws if w in event_text), None)
        matched_read = next((w for w in read_kws if w in event_text), None)
        matched_nav = next((w for w in nav_kws if w in event_text), None)
        matched_open = next((w for w in open_kws if w in event_text), None)

        if matched_input:
            evidence.append(f"Event keyword '{matched_input}' indicates a text-input interaction")
            confidence = 0.65
        elif matched_click:
            evidence.append(f"Event keyword '{matched_click}' indicates a pointer/activation interaction")
            confidence = 0.55
        elif matched_read:
            evidence.append(f"Event keyword '{matched_read}' indicates a data-read operation")
            confidence = 0.55
        elif matched_nav:
            evidence.append(f"Event keyword '{matched_nav}' indicates a navigation action")
            confidence = 0.50
        elif matched_open:
            evidence.append(f"Event keyword '{matched_open}' indicates an application or resource open action")
            confidence = 0.50
        else:
            evidence.append("No strong action keyword matched; activity inferred from event sequence heuristics")
            confidence = 0.4

        is_web = self._is_web_group(event_group)
        if is_web:
            url = next(
                (e.attributes.get("browser_url") or e.attributes.get("url")
                 for e in event_group
                 if e.attributes.get("browser_url") or e.attributes.get("url")),
                None,
            )
            if url:
                evidence.append(f"Attribute 'browser_url' = '{url}' identifies web execution context")
            else:
                evidence.append("Browser-related attributes present, identifying web execution context")
        else:
            app_val = next(
                (e.attributes.get("application") or e.attributes.get("app")
                 for e in event_group
                 if e.attributes.get("application") or e.attributes.get("app")),
                None,
            )
            if app_val:
                evidence.append(f"Attribute 'application' = '{app_val}' identifies desktop execution context")

        attrs = self._collect_attributes(event_group)
        el_id = attrs.get("element_id") or attrs.get("id")
        tag = attrs.get("tag_name") or attrs.get("tag_type")
        if el_id and not self._is_opaque_identifier(str(el_id)):
            evidence.append(f"Element identifier '{el_id}' pinpoints the target UI element")
        elif tag:
            evidence.append(f"Element tag '{tag}' describes the type of UI element targeted")

        reasoning = f"Rule-based inference: '{action}' action on '{target}' derived from event keywords and available attributes."

        result = {
            "activity_name": name,
            "requires_find": requires_find,
            "confidence": confidence,
            "evidence": evidence,
            "reasoning": reasoning,
        }
        if find_target:
            result["find_target"] = find_target
        return result

    def _mock_infer(self, event_group: List[Event]) -> Activity:
        """Mock inference returning an Activity (used by legacy infer_activity callers)."""
        result = self._mock_infer_result(event_group)
        source_events = [e.row_index for e in event_group if e.row_index is not None]
        return Activity(
            name=result["activity_name"],
            confidence=result["confidence"],
            evidence=result.get("evidence", []),
            reasoning=result.get("reasoning", ""),
            source_events=source_events,
        )
