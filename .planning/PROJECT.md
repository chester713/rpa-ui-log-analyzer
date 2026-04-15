# PROJECT.md — RPA UI Log Analyzer

## What This Is

An AI-powered recommendation system that analyzes UI interaction logs (CSV format) and suggests appropriate automation methods based on a defined set of RPA UI interaction patterns.

## Problem

Users need to automate repetitive UI tasks, but determining which automation method to use requires analyzing UI logs and mapping observed interactions to suitable methods. This is a manual, expertise-driven process.

## Solution

A system that:
1. Reads UI logs (CSV) following the Abb & Rehse reference data model
2. Groups events by shared context (same object, URL, etc.)
3. Logically infers the underlying activity from event patterns
4. Matches inferred activity against RPA UI interaction patterns
5. Recommends applicable Method(s) with the inferred activity

## Core Value

**Automate method selection** — transform raw UI events into actionable automation recommendations, bridging the gap between observed user behavior and RPA implementation.

---

## Requirements

### Input

- **Format**: CSV file
- **Required columns**: Event data (at minimum an "events" column per Abb & Rehse model)
- **Optional columns**: Object attributes (HTML id, cell reference, worksheet, workbook, etc.) that provide context for activity inference

### Processing Pipeline

1. **Event Parsing**
   - Read and validate CSV structure
   - Extract event descriptions and associated context attributes

2. **Activity Inference**
   - Group events by shared data context (same HTML id, URL, etc.)
   - Apply logical interpretation to determine the underlying activity
   - Handle one-to-many: multiple events → one activity
   - Handle one-to-one: single event → single activity

3. **Pattern Matching**
   - Match inferred activity against RPA UI interaction pattern definitions
   - Consider execution context (environment, object attributes)
   - Determine applicable patterns

4. **Method Recommendation**
   - Extract applicable Method from matched patterns
   - Methods are building blocks: "DOM Parsing", "UIA Tree Parsing", "Visual Recognition", "Hardware Simulation" (Extraction) or "DOM Manipulation", "UIA Tree Manipulation", "Hardware Simulation" (Modification)

### Output

- **Format**: Structured recommendation per inferred activity
- **Content**:
  - Inferred activity (what action was performed)
  - Recommended method (automation building block)
  - Mapping to source events (how events map to activity)

---

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use Abb & Rehse reference model | Standard data model for process-related UI logs | Ensures interoperability |
| Output includes inferred activity | Multiple events can map to one activity; method must be traceable to events | Provides full traceability |
| Standalone tool approach | No existing RPA platform integration requirement | Focused, portable solution |

---

## Scope

### In Scope

- CSV input parsing (Abb & Rehse model)
- Event grouping by context
- Activity inference engine
- Pattern library (pre-defined RPA UI interaction patterns)
- Method recommendation output
- Command-line interface

### Out of Scope

- RPA platform integration
- Bot generation/recording
- GUI for the tool
- Real-time log monitoring

---

## Success Criteria

- [ ] System accepts CSV input with event column and optional context attributes
- [ ] Events are correctly grouped by shared context
- [ ] Activities are inferred with logical interpretation
- [ ] Inferred activities are matched to RPA UI interaction patterns
- [ ] Applicable methods are recommended (Extraction or Modification category)
- [ ] Output includes inferred activity and recommended method with event mapping
- [ ] CLI tool is runnable with straightforward usage

---

*Last updated: 2026-04-15 after initialization*