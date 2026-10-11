"""Pattern matching module for RPA UI interaction patterns."""

from .pattern_loader import PatternLoader
from .pattern_matcher import (
    PatternMatcher,
    get_context_from_events,
    determine_environment,
    DEFAULT_ENVIRONMENT_COLUMNS,
)
from .output_formatter import RecommendationFormatter

_pattern_loader = PatternLoader()
PATTERNS = _pattern_loader.load_patterns("patterns")
matcher = PatternMatcher(PATTERNS)

__all__ = [
    "PatternLoader",
    "PatternMatcher",
    "get_context_from_events",
    "determine_environment",
    "DEFAULT_ENVIRONMENT_COLUMNS",
    "RecommendationFormatter",
    "PATTERNS",
    "matcher",
]
