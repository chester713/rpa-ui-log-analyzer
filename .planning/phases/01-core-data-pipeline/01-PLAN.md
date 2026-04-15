---
phase: 1
plan: 01
type: implementation
wave: 1
depends_on: []
files_modified: ["src/parser/csv_loader.py", "src/parser/event_log.py", "src/models/event.py", "src/models/activity.py", "src/inference/event_grouper.py", "src/inference/activity_inferrer.py", "src/mapping/event_activity_mapper.py", "tests/test_parser.py", "tests/test_inference.py"]
autonomous: false
requirements: [REQ-01, REQ-02]
---

<objective>
Build the core data pipeline that parses CSV UI logs into event logs and infers activities from event sequences with LLM-powered logical interpretation.
</objective>

<tasks>
## Task 1: Create project structure and CSV loader

**Type:** implementation

**Files:**
- `src/__init__.py` - Package init
- `src/parser/__init__.py` - Parser module init
- `src/parser/csv_loader.py` - CSV file loading and validation
- `src/models/__init__.py` - Models module init

**Action:**
Create project structure and implement CSV loader that:
- Reads CSV file from provided path
- Validates required `event` column exists (raises error if missing)
- Loads all other columns as optional event attributes
- Returns events as list of Event objects with attributes dict

**Acceptance Criteria:**
- [ ] `src/parser/csv_loader.py` contains `load_csv(filepath: str) -> List[Event]` function
- [ ] Function raises `ValueError` with message "Missing required column: event" if event column absent
- [ ] Function returns list where each Event has `event` field and `attributes` dict
- [ ] `tests/test_parser.py` contains test that verifies ValueError raised for missing event column
- [ ] `tests/test_parser.py` contains test that verifies optional columns loaded into attributes

**Read First:**
- `.planning/PROJECT.md` — Input format specifications
- `.planning/REQUIREMENTS.md` — REQ-01 requirements

---

## Task 2: Create Event and Activity data models

**Type:** implementation

**Files:**
- `src/models/event.py` - Event data model
- `src/models/activity.py` - Activity data model

**Action:**
Create data models with these exact structures:

`Event` class in `src/models/event.py`:
```python
class Event:
    def __init__(self, event: str, attributes: dict = None, row_index: int = None):
        self.event = event
        self.attributes = attributes or {}
        self.row_index = row_index
```

`Activity` class in `src/models/activity.py`:
```python
class Activity:
    def __init__(self, name: str, confidence: float, evidence: list = None, source_events: list = None):
        self.name = name
        self.confidence = confidence  # 0.0 to 1.0
        self.evidence = evidence or []  # Attribute breakdown
        self.source_events = source_events or []  # Event row indices
```

`EventActivityMapping` class:
```python
@dataclass
class EventActivityMapping:
    activity: Activity
    events: List[Event]
    confidence: float
    attribute_breakdown: dict
```

**Acceptance Criteria:**
- [ ] `src/models/event.py` contains Event class with exact signature above
- [ ] `src/models/activity.py` contains Activity class with exact signature above
- [ ] `src/models/activity.py` contains EventActivityMapping dataclass
- [ ] Tests verify Event stores attributes correctly
- [ ] Tests verify Activity stores confidence, evidence, and source_events

**Read First:**
- `.planning/phases/01-core-data-pipeline/01-CONTEXT.md` — Mapping structure decisions

---

## Task 3: Implement event grouping logic

**Type:** implementation

**Files:**
- `src/inference/__init__.py` - Inference module init
- `src/inference/event_grouper.py` - Event grouping logic

**Action:**
Implement `EventGrouper` class in `src/inference/event_grouper.py`:

```python
class EventGrouper:
    def __init__(self, group_attributes: List[str] = None):
        # group_attributes: which attributes define a group
        # Default: ['app', 'webpage', 'element_id', 'url']
        self.group_attributes = group_attributes or ['app', 'webpage', 'element_id', 'url']
    
    def group_events(self, events: List[Event]) -> List[List[Event]]:
        # Group consecutive events that share attributes
        # Returns list of event groups (each group is a list of Events)
        pass
```

Grouping logic:
1. Iterate through events in order
2. Start new group when: consecutive event shares at least one grouping attribute value
3. Attributes match if both have the attribute with same non-empty value
4. Return list of event groups

**Acceptance Criteria:**
- [ ] `EventGrouper` class exists in `src/inference/event_grouper.py`
- [ ] `group_events()` method returns `List[List[Event]]`
- [ ] Events with shared `app` attribute are grouped together
- [ ] Events with shared `webpage` or `element_id` are grouped together
- [ ] `tests/test_inference.py` contains test: two events with same app → same group
- [ ] `tests/test_inference.py` contains test: events without shared attrs → different groups

**Read First:**
- `.planning/phases/01-core-data-pipeline/01-CONTEXT.md` — Event grouping strategy

---

## Task 4: Implement LLM-powered activity inference

**Type:** implementation

**Files:**
- `src/inference/activity_inferrer.py` - LLM activity inference

**Action:**
Implement `ActivityInferrer` class in `src/inference/activity_inferrer.py`:

```python
class ActivityInferrer:
    def __init__(self, llm_client):
        self.llm_client = llm_client
    
    def infer_activity(self, event_group: List[Event]) -> Activity:
        # Use LLM to infer activity from event group
        # Prompt includes: event names, attributes, context
        # Returns Activity with name, confidence, evidence
        pass
    
    def infer_activities(self, event_groups: List[List[Event]]) -> List[Activity]:
        # Infer activity for each event group
        pass
```

LLM prompt template:
```
Given these UI events, infer the underlying user activity:

Events:
{event_list}

Attributes:
{attribute_dict}

What activity was the user performing? 
Provide a concise activity name (verb + object format, e.g., "Fill login form", "Select menu item").

Confidence (0.0-1.0): [score]
Evidence: [which attributes support this inference]
```

**Acceptance Criteria:**
- [ ] `ActivityInferrer` class exists with `infer_activity()` and `infer_activities()` methods
- [ ] LLM is called with structured prompt including events and attributes
- [ ] Returns Activity with name, confidence (float), evidence (list)
- [ ] Multiple event groups produce multiple Activity objects
- [ ] Tests mock LLM client and verify correct prompt construction

**Read First:**
- `.planning/phases/01-core-data-pipeline/01-CONTEXT.md` — Activity inference approach
- Check for existing LLM client patterns in codebase

---

## Task 5: Implement event-to-activity mapping

**Type:** implementation

**Files:**
- `src/mapping/__init__.py` - Mapping module init
- `src/mapping/event_activity_mapper.py` - Event-activity mapping

**Action:**
Implement `EventActivityMapper` class in `src/mapping/event_activity_mapper.py`:

```python
class EventActivityMapper:
    def __init__(self, grouper: EventGrouper, inferrer: ActivityInferrer):
        self.grouper = grouper
        self.inferrer = inferrer
    
    def map(self, events: List[Event]) -> List[EventActivityMapping]:
        # 1. Group events
        groups = self.grouper.group_events(events)
        
        # 2. Infer activity for each group
        activities = self.inferrer.infer_activities(groups)
        
        # 3. Create mappings
        mappings = []
        for group, activity in zip(groups, activities):
            mapping = EventActivityMapping(
                activity=activity,
                events=group,
                confidence=activity.confidence,
                attribute_breakdown=self._build_attribute_breakdown(group)
            )
            mappings.append(mapping)
        
        return mappings
    
    def _build_attribute_breakdown(self, event_group: List[Event]) -> dict:
        # Collect all attributes across group and count occurrences
        pass
```

**Acceptance Criteria:**
- [ ] `EventActivityMapper` class exists in `src/mapping/event_activity_mapper.py`
- [ ] `map()` returns `List[EventActivityMapping]`
- [ ] Each mapping contains: activity, events list, confidence, attribute_breakdown
- [ ] `attribute_breakdown` shows which attributes were used for inference
- [ ] Integration test verifies full pipeline: CSV → events → groups → activities → mappings

**Read First:**
- `.planning/phases/01-core-data-pipeline/01-CONTEXT.md` — Mapping structure

---

## Task 6: Create main pipeline orchestrator

**Type:** implementation

**Files:**
- `src/pipeline/__init__.py` - Pipeline module init
- `src/pipeline/data_pipeline.py` - Main orchestrator

**Action:**
Implement `DataPipeline` class in `src/pipeline/data_pipeline.py`:

```python
class DataPipeline:
    def __init__(self, csv_path: str, llm_client=None):
        self.csv_path = csv_path
        self.loader = CSVLoader()
        self.grouper = EventGrouper()
        self.inferrer = ActivityInferrer(llm_client)
        self.mapper = EventActivityMapper(self.grouper, self.inferrer)
    
    def run(self) -> PipelineResult:
        # Full pipeline execution
        # Returns PipelineResult with activities and mappings
        pass

@dataclass
class PipelineResult:
    activities: List[Activity]
    mappings: List[EventActivityMapping]
    statistics: dict  # event count, group count, etc.
```

**Acceptance Criteria:**
- [ ] `DataPipeline` class exists in `src/pipeline/data_pipeline.py`
- [ ] `run()` method executes full pipeline
- [ ] Returns PipelineResult with activities, mappings, statistics
- [ ] Error handling for missing event column
- [ ] Tests verify pipeline produces expected output structure

---

## Task 7: Create CLI entry point

**Type:** implementation

**Files:**
- `src_cli.py` - CLI entry point
- `requirements.txt` - Dependencies

**Action:**
Create CLI using argparse:

```python
# src_cli.py
import argparse

def main():
    parser = argparse.ArgumentParser(
        description='RPA UI Log Analyzer - Activity Inference'
    )
    parser.add_argument('csv_file', help='Path to CSV UI log file')
    parser.add_argument('--output', '-o', help='Output file path (JSON)')
    parser.add_argument('--verbose', '-v', action='store_true')
    
    args = parser.parse_args()
    
    # Run pipeline
    pipeline = DataPipeline(args.csv_file)
    result = pipeline.run()
    
    # Output results
    if args.output:
        # Write JSON
        pass
    else:
        # Print summary
        pass

if __name__ == '__main__':
    main()
```

**Acceptance Criteria:**
- [ ] `src_cli.py` exists and runs without errors
- [ ] `python src_cli.py --help` shows usage
- [ ] `python src_cli.py <csv_file>` runs pipeline and outputs results
- [ ] `--output` flag writes JSON file
- [ ] `--verbose` flag shows detailed output

**Read First:**
- `.planning/ROADMAP.md` — Phase 3 success criteria (for CLI patterns)

</tasks>

<verification>
## Verification Steps

1. **CSV Parser Verification:**
   - Run: `python -c "from src.parser.csv_loader import load_csv; load_csv('test.csv')"`
   - Expected: ValueError if event column missing
   - Run with valid CSV: Verify events returned with attributes

2. **Event Grouping Verification:**
   - Run: `python -c "from src.inference.event_grouper import EventGrouper; ..."`
   - Test with sample events: Verify grouping by shared attributes

3. **Activity Inference Verification:**
   - Run with mocked LLM: Verify prompt construction
   - Verify Activity objects have confidence, evidence, source_events

4. **Full Pipeline Verification:**
   - Run CLI with sample CSV: Verify output includes activities and mappings
   - Verify mapping contains confidence score and attribute breakdown

</verification>

<success_criteria>
- [ ] CSV file can be loaded and parsed as event log (REQ-01)
- [ ] Events are correctly grouped by logical interpretation with event attributes as supporting evidence (REQ-02 partial)
- [ ] Activities are inferred from event groups with mapping to source events (REQ-02)
- [ ] All tests pass: `python -m pytest tests/`
- [ ] CLI runs end-to-end: `python src_cli.py sample.csv`
</success_criteria>
