"""Pattern data model for RPA UI interaction patterns."""

from dataclasses import dataclass, field
from typing import List, Optional
import re


@dataclass
class Pattern:
    """RPA UI Interaction Pattern."""

    name: str
    action: str
    object: str
    method: str
    category: str  # "Extraction" or "Modification"
    contexts: List[str] = field(default_factory=list)
    description: str = ""

    def matches_activity(
        self, activity_action: str, activity_object: str, context: str
    ) -> bool:
        """
        Check if activity matches this pattern.

        Args:
            activity_action: Action from inferred activity
            activity_object: Object from inferred activity
            context: Execution context (web, desktop, visual)

        Returns:
            True if activity matches pattern in given context
        """
        action_match = activity_action.lower() == self.action.lower()
        object_match = activity_object.lower() == self.object.lower()
        context_valid = context in self.contexts if self.contexts else True
        return action_match and object_match and context_valid

    def get_method_for_context(self, context: str) -> Optional[str]:
        """
        Get the appropriate method for the given context.

        Args:
            context: Execution context (web, desktop, visual)

        Returns:
            Method string or None if context not supported
        """
        if context not in self.contexts:
            return None

        # Parse context-specific method from pattern text like:
        # "HTML DOM manipulation (Web) / UI Automation manipulation (Desktop) / Hardware simulation (Visual)"
        parts = [p.strip() for p in self.method.split("/")]
        for part in parts:
            lower = part.lower()
            if context == "web" and "(web" in lower:
                return re.sub(r"\s*\([^)]*\)\s*", "", part).strip()
            if context == "desktop" and "(desktop" in lower:
                return re.sub(r"\s*\([^)]*\)\s*", "", part).strip()
            if context == "visual" and "(visual" in lower:
                return re.sub(r"\s*\([^)]*\)\s*", "", part).strip()

        # Fallback to full method text when no explicit context marker found
        return self.method


@dataclass
class MethodRecommendation:
    """Recommendation result from pattern matching."""

    activity_name: str
    activity_action: str
    activity_object: str
    events: List[int]  # Source event row indices
    execution_environment: str
    pattern: Optional[Pattern]
    method: Optional[str]
    method_category: Optional[str]
    confidence: float
    context_switch: bool = False
    context_switch_from: Optional[str] = None
    context_switch_to: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for output."""
        return {
            "inferred_activity": self.activity_name,
            "activity_action": self.activity_action,
            "activity_object": self.activity_object,
            "events": self.events,
            "execution_environment": self.execution_environment,
            "pattern_matched": self.pattern.name if self.pattern else None,
            "method": self.method,
            "method_category": self.method_category,
            "confidence": self.confidence,
            "context_switch": self.context_switch,
            "context_switch_from": self.context_switch_from,
            "context_switch_to": self.context_switch_to,
        }
