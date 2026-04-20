"""LLM-powered activity inference."""

import os
import re
from urllib.parse import urlparse
from typing import List, Optional, Dict, Any
from ..models.event import Event
from ..models.activity import Activity


class ActivityInferrer:
    """Uses LLM to infer activities from event groups."""

    def __init__(self, llm_client=None):
        """
        Initialize ActivityInferrer.

        Args:
            llm_client: Client for LLM API. If None, uses a mock for testing.
        """
        self.llm_client = llm_client

    def infer_activity(self, event_group: List[Event]) -> Activity:
        """
        Infer activity from a group of events using LLM.

        Args:
            event_group: List of Events to analyze

        Returns:
            Activity with inferred name, confidence, and evidence
        """
        if not event_group:
            return Activity(name="Empty", confidence=0.0, evidence=[], source_events=[])

        if self.llm_client is None:
            return self._mock_infer(event_group)

        prompt = self._build_prompt(event_group)
        response = self.llm_client.complete(prompt)

        return self._parse_response(response, event_group)

    def infer_activities(self, event_groups: List[List[Event]]) -> List[Activity]:
        """
        Infer activities for multiple event groups.

        Args:
            event_groups: List of event groups

        Returns:
            List of Activities
        """
        return [self.infer_activity(group) for group in event_groups]

    def _build_prompt(self, event_group: List[Event]) -> str:
        """Build prompt for LLM to infer activity."""
        event_list = "\n".join(
            [
                f"- {e.event}"
                + (
                    f" ({e.attributes.get('element', '')})"
                    if e.attributes.get("element")
                    else ""
                )
                for e in event_group
            ]
        )

        attributes_summary = {}
        for e in event_group:
            for key, value in e.attributes.items():
                if value:
                    if key not in attributes_summary:
                        attributes_summary[key] = []
                    if value not in attributes_summary[key]:
                        attributes_summary[key].append(value)

        attr_list = "\n".join([f"- {k}: {v}" for k, v in attributes_summary.items()])

        prompt = f"""Given these UI events from a user interaction log, infer the underlying user activity.

Events (in temporal order):
{event_list}

Event attributes:
{attr_list or "No additional attributes"}

Based on these events, what activity was the user performing?
- Provide a concise activity name in verb + object + context format when possible
  (examples: "Click button on webpage", "Open workbook at C:\\Users\\...\\Downloads", "Paste value into text field")
- Rate your confidence from 0.0 to 1.0
- List which attributes support this inference

Respond in this format:
Activity: <name>
Confidence: <0.0-1.0>
Evidence: <attributes that support this inference>"""
        return prompt

    def _parse_response(self, response: str, event_group: List[Event]) -> Activity:
        """Parse LLM response into Activity object."""
        lines = response.strip().split("\n") if response else []
        name = ""
        confidence = 0.5
        evidence = []

        for line in lines:
            lower = line.lower().strip()
            if lower.startswith("activity:") or lower.startswith("activity name:"):
                name = re.sub(
                    r"^activity( name)?:", "", line, flags=re.IGNORECASE
                ).strip()
            elif lower.startswith("confidence:"):
                try:
                    confidence = float(
                        re.sub(r"^confidence:", "", line, flags=re.IGNORECASE).strip()
                    )
                except ValueError:
                    confidence = 0.5
            elif lower.startswith("evidence:"):
                evidence = [
                    e.strip()
                    for e in re.sub(r"^evidence:", "", line, flags=re.IGNORECASE).split(
                        ","
                    )
                    if e.strip()
                ]

        if not name or name.lower() == "unknown activity":
            name = self._derive_fallback_activity_name(event_group)
        else:
            name = self._post_process_inferred_name(name, event_group)

        source_events = [e.row_index for e in event_group if e.row_index is not None]

        return Activity(
            name=name,
            confidence=confidence,
            evidence=evidence,
            source_events=source_events,
        )

    def _post_process_inferred_name(self, name: str, event_group: List[Event]) -> str:
        """Correct common grouped-event mis-inferences."""
        event_text = " ".join([e.event.lower() for e in event_group])
        lower_name = (name or "").lower()

        # clickTextField + paste/changeField should infer Write activity,
        # where click is prerequisite focus.
        if (
            any(k in event_text for k in ["paste", "type", "input", "changefield"])
            and any(k in event_text for k in ["clicktextfield", "click"])
            and "click" in lower_name
        ):
            action, target, context = self._derive_activity_components(event_group)
            return self._compose_activity_name("Write", target, context)

        # Generic names create repetitive DFG roots; enrich from available attributes.
        if lower_name in {
            "activate element",
            "write element",
            "write html element on webpage",
            "navigate",
            "navigate in application",
            "interact with ui",
            "click element",
            "click element on webpage",
        }:
            action, target, context = self._derive_activity_components(event_group)
            return self._compose_activity_name(action, target, context)

        return name

    def _derive_fallback_activity_name(self, event_group: List[Event]) -> str:
        """Derive a meaningful fallback activity name from event content."""
        if not event_group:
            return "Unknown activity"

        action, target, context = self._derive_activity_components(event_group)
        return self._compose_activity_name(action, target, context)

    def _derive_activity_components(
        self, event_group: List[Event]
    ) -> tuple[str, str, Optional[str]]:
        """Infer action/target/context from grouped events and attributes."""
        if not event_group:
            return "Perform", "interaction", None

        event_text = " ".join([e.event.lower() for e in event_group])
        attrs = self._collect_attributes(event_group)

        if any(
            w in event_text
            for w in ["open", "newworkbook", "openworkbook", "openwindow", "launch"]
        ):
            action = "Open"
        elif any(
            w in event_text
            for w in ["paste", "type", "input", "changefield", "write", "fill", "enter"]
        ):
            action = "Write"
        elif any(w in event_text for w in ["click", "activate", "press", "tap"]):
            action = "Click"
        elif any(w in event_text for w in ["getcell", "read", "extract"]):
            action = "Read"
        elif any(
            w in event_text for w in ["select", "tab", "navigate", "startpage", "link"]
        ):
            action = "Navigate"
        else:
            action = "Perform"

        if self._is_web_group(event_group):
            target, context = self._build_web_target_context(attrs, event_group)
        else:
            target, context = self._build_desktop_target_context(attrs)

        return action, target, context

    def _compose_activity_name(
        self, action: str, target: str, context: Optional[str]
    ) -> str:
        """Compose readable Action + Target + Context activity name."""
        core = f"{(action or 'Perform').strip()} {(target or 'interaction').strip()}".strip()
        if context:
            return f"{core} {context}".strip()
        return core

    def _collect_attributes(self, event_group: List[Event]) -> Dict[str, Any]:
        """Collect first non-empty values for commonly used attributes."""
        key_order = [
            "element_id",
            "id",
            "tag_name",
            "tag_type",
            "xpath",
            "xpath_full",
            "browser_url",
            "url",
            "webpage",
            "application",
            "app",
            "workbook",
            "worksheet",
            "current_worksheet",
            "cell_range",
            "cell_range_number",
            "event_src_path",
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
            or str(e.attributes.get("application", "")).lower()
            in ["edge", "chrome", "firefox", "safari"]
            or str(e.attributes.get("category", "")).lower() == "browser"
            for e in event_group
        )

    def _build_web_target_context(
        self, attrs: Dict[str, Any], event_group: List[Event]
    ) -> tuple[str, Optional[str]]:
        tag = self._humanize_token(
            attrs.get("tag_name")
            or attrs.get("tag_type")
            or attrs.get("element_type")
            or "element"
        )
        element_id = attrs.get("element_id") or attrs.get("id")
        xpath = attrs.get("xpath") or attrs.get("xpath_full")
        url = attrs.get("browser_url") or attrs.get("url") or attrs.get("webpage")
        domain = self._extract_domain(url)

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

        context = " ".join(context_parts)
        return target, context

    def _build_web_locator_hint(
        self, xpath: Optional[str], event_group: List[Event]
    ) -> Optional[str]:
        """Build readable locator hints for repetitive web elements."""
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

        if not parts:
            return None

        return ", ".join(parts[:2])

    def _build_desktop_target_context(
        self, attrs: Dict[str, Any]
    ) -> tuple[str, Optional[str]]:
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
        if not host:
            return None
        return host

    def _build_webpage_hint(self, url: Optional[str]) -> Optional[str]:
        """Return human-readable webpage hint (domain + useful path)."""
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

        path = (parsed.path or "").strip()
        if path in {"", "/"}:
            return domain

        path = path.rstrip("/")
        return f"{domain}{path}"

    def _humanize_xpath(self, xpath: str) -> str:
        """Return a readable hint from xpath without exposing opaque full path."""
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
        """Extract row-like context from xpath when present (tr/li indices)."""
        text = str(xpath)
        row_match = re.search(r"/(?:tr|li)\[(\d+)\]", text, flags=re.IGNORECASE)
        if row_match:
            return f"row {row_match.group(1)}"
        return None

    def _derive_row_index_hint(self, event_group: List[Event]) -> Optional[str]:
        """Fallback row hint from source log position for disambiguation."""
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
        text = text.replace("_", " ").replace("-", " ")
        text = re.sub(r"\s+", " ", text)
        return text

    def _is_opaque_identifier(self, value: str) -> bool:
        text = str(value).strip()
        if not text:
            return True

        # Locator-like values (xpath/css-ish) are structured and can be humanized.
        if any(token in text for token in ["/", "[", "]", "@", "="]):
            return False

        # Avoid exposing long machine identifiers/GUID-like values in names.
        if len(text) >= 40 and " " not in text:
            return True
        if re.fullmatch(r"[0-9a-fA-F\-]{24,}", text):
            return True
        return False

    def _mock_infer(self, event_group: List[Event]) -> Activity:
        """Mock inference for testing without LLM."""
        event_text = " ".join([e.event.lower() for e in event_group])
        source_events = [e.row_index for e in event_group if e.row_index is not None]

        action, target, context = self._derive_activity_components(event_group)
        name = self._compose_activity_name(action, target, context)

        if any(
            w in event_text for w in ["type", "fill", "input", "paste", "changefield"]
        ):
            confidence = 0.8
        elif any(w in event_text for w in ["click", "select", "press"]):
            confidence = 0.7
        elif any(w in event_text for w in ["scroll", "navigate", "change"]):
            confidence = 0.6
        else:
            confidence = 0.5

        evidence = list(set(attr for e in event_group for attr in e.attributes.keys()))

        return Activity(
            name=name,
            confidence=confidence,
            evidence=evidence,
            source_events=source_events,
        )
