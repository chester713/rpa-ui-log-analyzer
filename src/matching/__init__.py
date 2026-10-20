"""Pattern matching module for RPA UI interaction patterns."""

from .pattern_loader import PatternLoader
from .pattern_matcher import (
    PatternMatcher,
    get_context_from_events,
    determine_environment,
    DEFAULT_ENVIRONMENT_COLUMNS,
)
from .output_formatter import RecommendationFormatter

import os as _os

# The pattern files live in <repository>/patterns, wherever the app is started from.
_PATTERNS_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "patterns")
_pattern_loader = PatternLoader()
PATTERNS = _pattern_loader.load_patterns(_PATTERNS_DIR)
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
