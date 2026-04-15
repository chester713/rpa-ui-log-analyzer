---
wave: 1
depends_on: []
files_modified:
  - src/matching/pattern_matcher.py (new)
  - src/matching/__init__.py (new)
  - src/models/pattern.py (new)
  - patterns/*.md (new, 13 files)
  - tests/test_matching.py (new)
requirements_addressed:
  - REQ-03
  - REQ-04
---

<objective>
Create pattern system for storing RPA UI interaction patterns and matching inferred activities to recommend methods.
</objective>

<tasks>

<task>
<read_first>
- src/models/activity.py (Phase 1 output structure)
- src/inference/activity_inferrer.py (how activities are inferred)
- .planning/phases/02-pattern-system/02-CONTEXT.md (design decisions)
</read_first>

<action>
Create src/models/pattern.py with Pattern data model:

```python
@dataclass
class Pattern:
    name: str              # Pattern identifier (e.g., "activate element")
    action: str            # Action component (e.g., "activate")
    object: str            # Object component (e.g., "html element")
    method: str            # RPA method (e.g., "Element Activate")
    method_category: str  # "Extraction" or "Modification"
    contexts: List[str]    # Valid contexts: ["web", "desktop", "visual"]
    description: str       # Pattern description
    
    def matches_activity(self, activity: Activity, context: str) -> bool:
        """Check if activity matches this pattern."""
        action_match = activity.action.lower() == self.action.lower()
        object_match = activity.object.lower() == self.object.lower()
        context_valid = context in self.contexts
        return action_match and object_match and context_valid
```
</action>

<acceptance_criteria>
- src/models/pattern.py exists with Pattern dataclass
- Pattern includes: name, action, object, method, method_category, contexts, description
- matches_activity() method accepts Activity and context, returns bool
- Tests verify pattern matching logic
</acceptance_criteria>
</task>

<task>
<read_first>
- src/models/pattern.py (from task 1)
- .planning/REQUIREMENTS.md (REQ-03, REQ-04 requirements)
</read_first>

<action>
Create src/matching/pattern_matcher.py with PatternMatcher class:

```python
class PatternMatcher:
    def __init__(self, patterns: List[Pattern]):
        self.patterns = patterns
        
    def match(self, activity: Activity, context: str) -> Optional[Pattern]:
        """Find matching pattern for activity in given context."""
        for pattern in self.patterns:
            if pattern.matches_activity(activity, context):
                return pattern
        return None
    
    def match_all(self, activities: List[Activity], contexts: List[str]) -> List[Tuple[Activity, Optional[Pattern]]]:
        """Match all activities to patterns."""
        return [(act, self.match(act, ctx)) for act, ctx in zip(activities, contexts)]
```

Include method recommendation output:
```python
@dataclass
class MethodRecommendation:
    activity: Activity
    pattern: Optional[Pattern]
    method: Optional[str]
    method_category: Optional[str]  # "Extraction" or "Modification"
    confidence: float
```

Context extraction from event attributes:
- Extract from event.attributes: "app", "application", "environment", "platform"
- Default to "web" if no context found
</action>

<acceptance_criteria>
- src/matching/pattern_matcher.py exists with PatternMatcher class
- match() returns Optional[Pattern] for single activity
- match_all() returns list of (Activity, Pattern) tuples
- MethodRecommendation dataclass with activity, pattern, method, method_category, confidence
- Context extraction from event attributes (app/environment/platform)
- Tests verify matching with mock activities and patterns
</acceptance_criteria>
</task>

<task>
<read_first>
- src/matching/pattern_matcher.py (from task 2)
- src/models/pattern.py (from task 1)
</read_first>

<action>
Create pattern library with 13 skill.md files in patterns/ directory:

Each pattern file follows skill.md format:
```markdown
# Pattern: [pattern-name]

## Action
[action-verb]

## Object
[object-noun]

## Method
[rpa-method-name]

## Category
Extraction | Modification

## Contexts
- web
- desktop  
- visual

## Description
[pattern description]
```

Create the following 13 patterns:
1. patterns/01-activate-element.md - activate element → Element Activate (Modification)
2. patterns/02-type-text.md - type text → Type Into (Modification)
3. patterns/03-select-item.md - select item → Select Item (Modification)
4. patterns/04-extract-data.md - extract data → Get Text (Extraction)
5. patterns/05-click-button.md - click button → Click (Modification)
6. patterns/06-navigate-page.md - navigate page → Navigate to URL (Modification)
7. patterns/07-wait-element.md - wait element → Wait Element Vanish (Extraction)
8. patterns/08-screenshot.md - take screenshot → Screenshot (Extraction)
9. patterns/09-scroll-page.md - scroll page → Scroll (Modification)
10. patterns/10-hover-element.md - hover element → Hover (Modification)
11. patterns/11-check-checkbox.md - check checkbox → Check (Modification)
12. patterns/12-uncheck-checkbox.md - uncheck checkbox → Uncheck (Modification)
13. patterns/13-close-window.md - close window → Close Window (Modification)
</action>

<acceptance_criteria>
- patterns/ directory created with 13 pattern .md files
- Each pattern file has: Action, Object, Method, Category, Contexts, Description
- Pattern action+object maps to unique skill for exact matching
- Context variants handled (e.g., web→"html element", desktop→"ui element")
</acceptance_criteria>
</task>

<task>
<read_first>
- src/matching/pattern_matcher.py (from task 2)
- src/models/pattern.py (from task 1)
- src/pipeline/data_pipeline.py (how pipeline chains)
</read_first>

<action>
Create src/matching/pattern_loader.py to load patterns from .md files:

```python
class PatternLoader:
    def load_patterns(self, patterns_dir: str = "patterns") -> List[Pattern]:
        """Load all pattern .md files and parse to Pattern objects."""
        patterns = []
        for md_file in glob.glob(f"{patterns_dir}/*.md"):
            pattern = self._parse_pattern_file(md_file)
            patterns.append(pattern)
        return patterns
    
    def _parse_pattern_file(self, filepath: str) -> Pattern:
        """Parse skill.md file to extract pattern fields."""
        # Parse markdown: ## Action, ## Object, ## Method, ## Category, ## Contexts
        # Return Pattern object
```

Pattern loading at module level:
```python
# src/matching/__init__.py
from .pattern_loader import PatternLoader
from .pattern_matcher import PatternMatcher

# Load patterns on import
_pattern_loader = PatternLoader()
PATTERNS = _pattern_loader.load_patterns()
matcher = PatternMatcher(PATTERNS)
```
</action>

<acceptance_criteria>
- src/matching/pattern_loader.py exists with PatternLoader class
- load_patterns() reads all .md files in patterns/ directory
- _parse_pattern_file() extracts Action, Object, Method, Category, Contexts
- src/matching/__init__.py exports PatternMatcher with pre-loaded patterns
- Tests verify pattern loading from sample .md files
</acceptance_criteria>
</task>

<task>
<read_first>
- src/matching/pattern_matcher.py (tasks 2-4)
- src/pipeline/data_pipeline.py (Phase 1 pipeline)
</read_first>

<action>
Create output formatter for pattern matching results:

```python
class RecommendationFormatter:
    def format(self, recommendations: List[MethodRecommendation]) -> Dict[str, Any]:
        """Format recommendations as structured output."""
        return {
            "recommendations": [
                {
                    "inferred_activity": rec.activity.name,
                    "events": rec.activity.source_events,
                    "execution_environment": rec.context,
                    "pattern_matched": rec.pattern.name if rec.pattern else None,
                    "method": rec.method,
                    "method_category": rec.method_category,
                }
                for rec in recommendations
            ]
        }
    
    def to_csv(self, recommendations: List[MethodRecommendation], output_path: str):
        """Export recommendations to CSV."""
        # Columns: activity, source_events, environment, pattern, method, category
```

Add to PatternMatcher:
```python
def get_context_from_events(events: List[Event]) -> str:
    """Extract execution context from event attributes."""
    for event in events:
        if "app" in event.attributes: return "desktop"
        if "webpage" in event.attributes: return "web"
        if "element" in event.attributes and "visual" in event.attributes.get("type", ""): return "visual"
    return "web"  # default
```
</action>

<acceptance_criteria>
- src/matching/output_formatter.py exists with RecommendationFormatter
- format() returns dict with: inferred_activity, events, execution_environment, pattern_matched, method, method_category
- to_csv() exports recommendations to CSV with correct columns
- get_context_from_events() extracts from event attributes (app→desktop, webpage→web, visual element→visual)
- Tests verify output format matches REQ-04 requirements
</acceptance_criteria>
</task>

<task>
<read_first>
- src/matching/pattern_matcher.py
- src/pipeline/data_pipeline.py
</read_first>

<action>
Integrate pattern matching into data pipeline (src/pipeline/data_pipeline.py):

```python
# After activity inference, add pattern matching stage

# Import pattern matcher
from src.matching import PatternMatcher

# In pipeline process():
# 1. Load patterns (or use pre-loaded from __init__)
# 2. For each activity, extract context from associated events
# 3. Match activity to pattern
# 4. Create MethodRecommendation

# Pipeline stages:
# Stage 1: CSV → Events
# Stage 2: Events → Event Groups
# Stage 3: Event Groups → Activities
# Stage 4: Activities + Events → Pattern Match + Method Recommendation  [NEW]
# Stage 5: Output with activity-method mapping
```

Extend DataPipeline to include pattern matching output in results.
</action>

<acceptance_criteria>
- DataPipeline integrates PatternMatcher after activity inference
- Each activity matched to pattern with method recommendation
- Pipeline output includes: activity, events, context, pattern, method, category
- End-to-end test with sample.csv produces valid recommendations
- All REQ-03, REQ-04 success criteria verified
</acceptance_criteria>
</task>

<task>
<read_first>
- src/matching/pattern_matcher.py
- src/matching/pattern_loader.py
- src/matching/output_formatter.py
</read_first>

<action>
Create tests/test_matching.py with comprehensive test coverage:

```python
# Test Pattern model
def test_pattern_creation():
    p = Pattern("activate", "activate", "element", "Element Activate", "Modification", ["web"], "desc")
    assert p.action == "activate"
    
def test_pattern_matches_activity():
    p = Pattern("activate", "activate", "element", "Element Activate", "Modification", ["web"], "desc")
    activity = Activity("activate element", 0.8)
    activity.action = "activate"
    activity.object = "element"
    assert p.matches_activity(activity, "web") == True

# Test PatternMatcher
def test_match_returns_pattern():
    patterns = [Pattern(...)]
    matcher = PatternMatcher(patterns)
    result = matcher.match(activity, "web")
    assert result is not None

# Test PatternLoader
def test_load_patterns():
    loader = PatternLoader()
    patterns = loader.load_patterns("patterns")
    assert len(patterns) == 13

# Test output format
def test_recommendation_output():
    formatter = RecommendationFormatter()
    formatted = formatter.format([rec])
    assert "inferred_activity" in formatted["recommendations"][0]
```
</action>

<acceptance_criteria>
- tests/test_matching.py exists with 10+ test functions
- Tests cover: Pattern model, PatternMatcher, PatternLoader, RecommendationFormatter
- All existing tests pass: pytest runs without errors
- Coverage includes both success and edge cases
</acceptance_criteria>
</task>

</tasks>

<must_haves>
- Pattern library with 13 RPA UI interaction patterns (REQ-03)
- Pattern matching on Action + Object (REQ-04)
- Context weighting for web/desktop/visual variants (REQ-04)
- Method output in Extraction/Modification categories (REQ-04)
- Event-to-activity-to-method mapping for traceability (REQ-04)
</must_haves>

<success_criteria>
1. Pattern library stores RPA UI interaction patterns with Action, Object, Method, Context structure
2. Inferred activities are matched to patterns considering execution context (web/desktop/visual)
3. Recommended methods are output in correct categories (Extraction/Modification)
</success_criteria>

---

## PLANNING COMPLETE

Phase 2 plan: 7 tasks in 1 wave covering:
- Pattern data model
- Pattern matching logic
- 13 pattern skill.md files
- Pattern loader from .md files
- Output formatter
- Pipeline integration
- Test coverage