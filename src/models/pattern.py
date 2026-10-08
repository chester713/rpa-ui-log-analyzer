"""Pattern data model for RPA UI interaction patterns."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import re

# The pattern files label the screen environment "Visual".
_LABEL_ALIASES = {"visual": "screen"}
_KNOWN_ENVIRONMENTS = ("web", "desktop", "screen")


def _split_top_level(text: str, separator: str) -> List[str]:
    """Split on ``separator`` only where it is outside parentheses.

    Method labels such as "(Web/Desktop/Screen)" contain the separator
    themselves, so a plain ``str.split`` would cut them apart.
    """
    parts, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == separator and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


@dataclass
class Pattern:
    """RPA UI Interaction Pattern."""

    name: str
    action: str
    object: str
    method: str
    category: str  # "Extraction", "Modification", or "Control"
    contexts: List[str] = field(default_factory=list)
    description: str = ""
    # environment -> why the pattern has no variant there (optional, from the pattern file)
    unsupported_reasons: Dict[str, str] = field(default_factory=dict)

    def matches_activity(
        self, activity_action: str, activity_object: str, context: str
    ) -> bool:
        """
        Check if activity matches this pattern.

        Args:
            activity_action: Action from inferred activity
            activity_object: Object from inferred activity
            context: Execution context (web, desktop, screen, unknown)

        Returns:
            True if activity matches pattern in given context
        """
        action_match = activity_action.lower() == self.action.lower()
        object_match = activity_object.lower() == self.object.lower()
        context_valid = context in self.contexts if self.contexts else True
        return action_match and object_match and context_valid

    def get_method_for_context(self, context: str) -> Optional[str]:
        """
        Get the recommended method for the given execution environment.

        The pattern's Method field lists one variant per environment, highest
        fidelity first, each followed by the environments it applies to, e.g.
        "HTML DOM manipulation (Web) / UI Automation manipulation (Desktop) /
        Hardware simulation (Visual)". A label may cover several environments
        ("Hardware simulation (Web/Desktop/Screen)"), and "Visual" is the
        pattern files' name for the screen environment. The first variant whose
        label covers ``context`` is returned with its label stripped.

        Args:
            context: Execution context (web, desktop, screen, unknown)

        Returns:
            The method name, or None when the pattern does not support the
            context or defines no variant for it.
        """
        if context not in self.contexts:
            return None

        for variant in _split_top_level(self.method, "/"):
            match = re.fullmatch(r"(?P<name>[^()]*?)\s*\((?P<label>[^()]*)\)", variant.strip())
            if match is None:
                # Unlabelled variant: applies to every environment.
                return variant.strip() or None
            environments = {
                _LABEL_ALIASES.get(token.strip().lower(), token.strip().lower())
                for token in re.split(r"[/,]", match.group("label"))
            }
            if context in environments:
                return match.group("name").strip()

        return None


def explain_missing_method(pattern: Optional[Pattern], environment: str) -> Optional[str]:
    """Explain why no method can be recommended, or None when the pattern has one.

    Used by both the web pipeline and the CLI so they report the same reason.
    ``environment`` is the execution environment the method is looked up in.
    """
    if pattern is None:
        return "No method: no pattern matched this activity."
    if pattern.get_method_for_context(environment) is not None:
        return None
    if environment not in _KNOWN_ENVIRONMENTS:
        return "No method: the execution environment could not be determined from the log attributes."

    message = f"No method for the {environment} environment: {pattern.name} has no {environment} variant"
    reason = pattern.unsupported_reasons.get(environment)
    return f"{message} ({reason})." if reason else f"{message}."


@dataclass
class MethodRecommendation:
    """Recommendation result from pattern matching."""

    activity_name: str
    activity_action: Optional[str]
    activity_object: Optional[str]
    events: List[int]  # Source event row indices
    execution_environment: str
    pattern: Optional[Pattern]
    method: Optional[str]
    method_category: Optional[str]
    confidence: float
    confidence_explanation: Optional[str] = None
    context_attributes_used: Optional[List[str]] = None
    context_switch: bool = False
    context_switch_from: Optional[str] = None
    context_switch_to: Optional[str] = None
    inference_evidence: Optional[List[str]] = None
    inference_reasoning: Optional[str] = None
    method_note: Optional[str] = None  # why no method was recommended (None when one was)

    def to_dict(self) -> dict:
        """Convert to dictionary for output."""
        # Canonical REQ-06 output shape; required keys must remain present.
        recommendation_record = {
            "inferred_activity": self.activity_name,
            "activity_action": self.activity_action,
            "activity_object": self.activity_object,
            "events": self.events,
            "execution_environment": self.execution_environment,
            "pattern_matched": self.pattern.name if self.pattern else None,
            "method": self.method,
            "method_category": self.method_category,
            "confidence": self.confidence,
            "confidence_explanation": self.confidence_explanation,
            "context_attributes_used": self.context_attributes_used,
            "context_switch": self.context_switch,
            "context_switch_from": self.context_switch_from,
            "context_switch_to": self.context_switch_to,
            "inference_evidence": self.inference_evidence or [],
            "inference_reasoning": self.inference_reasoning or "",
            "method_note": self.method_note,
        }
        return recommendation_record
