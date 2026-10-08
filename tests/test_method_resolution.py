"""Method resolution follows each pattern's per-environment applicability.

Applicability is cumulative: web can use every method, desktop can use UI
Automation / visual recognition / hardware simulation, and screen can use only
visual recognition and hardware simulation. The recommended method is the
highest-fidelity variant the pattern defines for the detected environment.
"""

import pytest

from src.matching import PATTERNS
from src.models.pattern import Pattern

CONTEXTS = ("web", "desktop", "screen")
SCREEN_METHODS = {"visual recognition", "hardware simulation"}


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.name)
@pytest.mark.parametrize("context", CONTEXTS)
def test_resolves_one_technique_with_label_stripped(pattern: Pattern, context: str) -> None:
    method = pattern.get_method_for_context(context)

    if context not in pattern.contexts:
        assert method is None
        return

    assert method, f"{pattern.name} supports {context} but resolved no method"
    # A single technique name: no "(Web)" style label and no " / " variant list.
    assert "(" not in method and "/" not in method


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.name)
def test_screen_only_uses_visual_recognition_or_hardware_simulation(pattern: Pattern) -> None:
    method = pattern.get_method_for_context("screen")

    if method is not None:
        assert method.lower() in SCREEN_METHODS


@pytest.mark.parametrize("pattern", [p for p in PATTERNS if p.category == "Extraction"], ids=lambda p: p.name)
def test_extraction_patterns_use_visual_recognition_on_screen(pattern: Pattern) -> None:
    assert pattern.get_method_for_context("screen").lower() == "visual recognition"


@pytest.mark.parametrize(
    "pattern",
    [p for p in PATTERNS if p.category != "Extraction" and "screen" in p.contexts],
    ids=lambda p: p.name,
)
def test_modification_and_control_patterns_use_hardware_simulation_on_screen(pattern: Pattern) -> None:
    assert pattern.get_method_for_context("screen").lower() == "hardware simulation"


def _by_name(name: str) -> Pattern:
    return next(p for p in PATTERNS if p.name == name)


def test_hover_has_no_ui_automation_variant() -> None:
    hover = _by_name("Hover")

    assert hover.get_method_for_context("web") == "HTML DOM manipulation"
    assert hover.get_method_for_context("desktop") == "Hardware simulation"
    assert hover.get_method_for_context("screen") == "Hardware simulation"


def test_pattern_scope_exceptions_are_respected() -> None:
    assert _by_name("Delete Element").get_method_for_context("screen") is None
    assert _by_name("Switch Context").get_method_for_context("web") is None
    assert _by_name("Switch Context").get_method_for_context("screen") is None
    assert _by_name("Switch Context").get_method_for_context("desktop") == "UI Automation manipulation"


def test_multi_environment_label_is_not_split_apart() -> None:
    pattern = Pattern(
        name="Example",
        action="Do",
        object="Element",
        method="DOM thing (Web) / Shared thing (Web/Desktop/Screen)",
        category="Control",
        contexts=["web", "desktop", "screen"],
    )

    assert pattern.get_method_for_context("web") == "DOM thing"
    assert pattern.get_method_for_context("desktop") == "Shared thing"
    assert pattern.get_method_for_context("screen") == "Shared thing"


def test_variant_missing_for_a_supported_context_resolves_to_none() -> None:
    pattern = Pattern(
        name="Example",
        action="Do",
        object="Element",
        method="DOM thing (Web)",
        category="Control",
        contexts=["web", "desktop"],
    )

    assert pattern.get_method_for_context("web") == "DOM thing"
    assert pattern.get_method_for_context("desktop") is None
