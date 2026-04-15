"""LLM-powered activity inference."""

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
- Provide a concise activity name in verb + object format (e.g., "Fill login form", "Select menu item", "Click submit button")
- Rate your confidence from 0.0 to 1.0
- List which attributes support this inference

Respond in this format:
Activity: <name>
Confidence: <0.0-1.0>
Evidence: <attributes that support this inference>"""
        return prompt

    def _parse_response(self, response: str, event_group: List[Event]) -> Activity:
        """Parse LLM response into Activity object."""
        lines = response.strip().split("\n")
        name = "Unknown Activity"
        confidence = 0.5
        evidence = []

        for line in lines:
            if line.startswith("Activity:"):
                name = line.replace("Activity:", "").strip()
            elif line.startswith("Confidence:"):
                try:
                    confidence = float(line.replace("Confidence:", "").strip())
                except ValueError:
                    confidence = 0.5
            elif line.startswith("Evidence:"):
                evidence = [e.strip() for e in line.replace("Evidence:", "").split(",")]

        source_events = [e.row_index for e in event_group if e.row_index is not None]

        return Activity(
            name=name,
            confidence=confidence,
            evidence=evidence,
            source_events=source_events,
        )

    def _mock_infer(self, event_group: List[Event]) -> Activity:
        """Mock inference for testing without LLM."""
        event_text = " ".join([e.event.lower() for e in event_group])
        source_events = [e.row_index for e in event_group if e.row_index is not None]

        if any(w in event_text for w in ["click", "select", "press"]):
            name = "Click element"
            confidence = 0.7
        elif any(w in event_text for w in ["type", "fill", "input", "paste"]):
            name = "Enter text"
            confidence = 0.7
        elif any(w in event_text for w in ["scroll", "navigate", "change"]):
            name = "Navigate"
            confidence = 0.6
        else:
            name = "Interact with UI"
            confidence = 0.5

        evidence = list(set(attr for e in event_group for attr in e.attributes.keys()))

        return Activity(
            name=name,
            confidence=confidence,
            evidence=evidence,
            source_events=source_events,
        )
