"""Activity data model for inferred activities."""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from .event import Event


class Activity:
    """Represents an inferred user activity from event sequences."""

    def __init__(
        self,
        name: str,
        confidence: float,
        evidence: Optional[List[str]] = None,
        reasoning: Optional[str] = None,
        source_events: Optional[List[int]] = None,
        activity_type: str = "main",
        is_implicit: bool = False,
        group_index: int = 0,
    ):
        self.name = name
        self.confidence = max(0.0, min(1.0, confidence))
        self.evidence = evidence or []
        self.reasoning = reasoning or ""
        self.source_events = source_events or []
        self.activity_type = activity_type  # "main", "prerequisite", "context_switch"
        self.is_implicit = is_implicit
        self.group_index = group_index

    def __repr__(self) -> str:
        return f"Activity(name='{self.name}', type='{self.activity_type}', confidence={self.confidence})"

    def __eq__(self, other) -> bool:
        if not isinstance(other, Activity):
            return False
        return self.name == other.name and self.confidence == other.confidence


@dataclass
class EventActivityMapping:
    """Maps a group of events to an inferred activity."""

    activity: Activity
    events: List[Event]
    confidence: float
    attribute_breakdown: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "activity": {
                "name": self.activity.name,
                "confidence": self.activity.confidence,
                "evidence": self.activity.evidence,
                "reasoning": self.activity.reasoning,
                "source_events": self.activity.source_events,
                "activity_type": self.activity.activity_type,
                "is_implicit": self.activity.is_implicit,
            },
            "events": [
                {"event": e.event, "attributes": e.attributes, "row_index": e.row_index}
                for e in self.events
            ],
            "confidence": self.confidence,
            "attribute_breakdown": self.attribute_breakdown,
        }
