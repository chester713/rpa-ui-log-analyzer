"""Pattern data model for RPA UI interaction patterns."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import re

# The pattern files label the screen environment "Visual".
_LABEL_ALIASES = {"visual": "screen"}
_KNOWN_ENVIRONMENTS = ("web", "desktop", "screen")

# Environments ordered from richest to poorest interface information. Applicability is
# cumulative: an environment can use the methods of its own level and of every poorer
# level (web → content, accessibility and visual/input-level methods; desktop →
# accessibility and visual/input-level; screen → visual/input-level only).
_ENVIRONMENT_RANK = {"web": 0, "desktop": 1, "screen": 2}

# At most one method per level, so a prioritised list never holds more than three.
MAX_RECOMMENDED_METHODS = 3

# Object type of an element in each execution environment. The type is a property of
# the object: choosing a poorer method (e.g. hardware simulation on an HTML element)
# does not change it.
OBJECT_TYPE_BY_ENVIRONMENT = {"web": "HTML element", "desktop": "UI element", "screen": "visual element"}


def method_level(method_name: str) -> Optional[int]:
    """The level of a method by its family, or None when the family is not recognised.

    0 — content-level (DOM parsing/manipulation): acts only on HTML elements;
    1 — accessibility-level (UI Automation): acts on UI elements and HTML elements;
    2 — visual recognition and hardware simulation: act on any object.
    """
    name = method_name.lower()
    if "dom" in name or "html" in name:
        return 0
    if "ui automation" in name or "uia" in name:
        return 1
    if "visual" in name or "hardware" in name:
        return 2
    return None


def object_type_for(pattern: Optional["Pattern"], environment: str) -> Optional[str]:
    """The object type of an activity: HTML, UI or visual element by environment.

    Patterns whose object class is not an element (Switch Context acts on a context)
    keep their own object class.
    """
    if pattern is None:
        return None
    if (pattern.object or "").strip().lower() != "element":
        return pattern.object or None
    return OBJECT_TYPE_BY_ENVIRONMENT.get(environment)


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

    def _variants(self) -> List[tuple]:
        """The Method field as (method name, level) pairs, in the order written.

        The Method field lists one variant per environment, each followed by the
        environments it is written for, e.g. "HTML DOM manipulation (Web) / UI
        Automation manipulation (Desktop) / Hardware simulation (Visual)". A label
        may cover several environments ("Hardware simulation (Web/Desktop/Screen)"),
        and "Visual" is the pattern files' name for the screen environment.

        A variant's level is determined by its method family (see ``method_level``):
        DOM methods are content-level, UI Automation methods accessibility-level, and
        visual recognition and hardware simulation act on any object. Only when the
        family is not recognised does the label decide (the poorest environment it
        names); an unlabelled, unrecognised variant ranks as screen level.
        """
        variants = []
        for variant in _split_top_level(self.method, "/"):
            text = variant.strip()
            if not text:
                continue
            match = re.fullmatch(r"(?P<name>[^()]*?)\s*\((?P<label>[^()]*)\)", text)
            name = match.group("name").strip() if match else text
            family_level = method_level(name)
            if family_level is not None:
                variants.append((name, family_level))
                continue
            if match is None:
                variants.append((text, _ENVIRONMENT_RANK["screen"]))
                continue
            ranks = [
                _ENVIRONMENT_RANK[env]
                for env in (
                    _LABEL_ALIASES.get(token.strip().lower(), token.strip().lower())
                    for token in re.split(r"[/,]", match.group("label"))
                )
                if env in _ENVIRONMENT_RANK
            ]
            if ranks:
                variants.append((match.group("name").strip(), max(ranks)))
        return variants

    def get_methods_for_context(self, context: str) -> List[str]:
        """
        Get the prioritised list of methods applicable in an execution environment.

        Applicability is cumulative: a method is applicable in ``context`` when its
        level is the same as or poorer than the environment's own level, so a web
        environment can use content-, accessibility- and visual/input-level methods,
        a desktop environment accessibility- and visual/input-level methods, and a
        screen environment visual/input-level methods only. The list is ordered by
        level — content-level first, then accessibility-level, then visual/input-level
        — keeping the pattern file's order within a level, and holds at most
        ``MAX_RECOMMENDED_METHODS`` entries.

        Args:
            context: Execution context (web, desktop, screen, unknown)

        Returns:
            Method names, highest priority first. Empty when the pattern does not
            support the context or defines no applicable variant.
        """
        if context not in self.contexts or context not in _ENVIRONMENT_RANK:
            return []

        floor = _ENVIRONMENT_RANK[context]
        applicable = sorted(
            (v for v in self._variants() if v[1] >= floor),
            key=lambda v: v[1],  # stable: keeps the file's order within a level
        )
        methods: List[str] = []
        for name, _level in applicable:
            if name not in methods:
                methods.append(name)
        return methods[:MAX_RECOMMENDED_METHODS]

    def get_method_for_context(self, context: str) -> Optional[str]:
        """
        Get the top-priority method for the given execution environment.

        Args:
            context: Execution context (web, desktop, screen, unknown)

        Returns:
            The first method of ``get_methods_for_context``, or None when there is none.
        """
        methods = self.get_methods_for_context(context)
        return methods[0] if methods else None


def explain_missing_method(pattern: Optional[Pattern], environment: str) -> Optional[str]:
    """Explain why no method can be recommended, or None when the pattern has one.

    Used by both the web pipeline and the CLI so they report the same reason.
    ``environment`` is the execution environment the method is looked up in.
    """
    if pattern is None:
        return "No method: no pattern matched this activity, which is not covered by the pattern collection."
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
    target: Optional[str] = None  # the concrete target element, e.g. "First Name field"
    # Prioritised methods (highest first, at most three); ``method`` is the first of them.
    methods: List[str] = field(default_factory=list)

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
            "methods": list(self.methods),
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
            "target": self.target,
        }
        return recommendation_record
