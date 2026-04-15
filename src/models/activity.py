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
        source_events: Optional[List[int]] = None,
    ):
        """
        Initialize an Activity.

        Args:
            name: Activity name in verb + object format (e.g., "Fill login form")
            confidence: Confidence score from 0.0 to 1.0
            evidence: List of attribute evidence that supported the inference
            source_events: List of source event row indices
        """
        self.name = name
        self.confidence = max(0.0, min(1.0, confidence))  # Clamp to 0-1
        self.evidence = evidence or []
        self.source_events = source_events or []

    def __repr__(self) -> str:
        return f"Activity(name='{self.name}', confidence={self.confidence})"

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
                "source_events": self.activity.source_events,
            },
            "events": [
                {"event": e.event, "attributes": e.attributes, "row_index": e.row_index}
                for e in self.events
            ],
            "confidence": self.confidence,
            "attribute_breakdown": self.attribute_breakdown,
        }
