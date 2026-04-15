# ROADMAP.md

## Project: RPA UI Log Analyzer

**Phases:** 3 | **Requirements:** 6 | **All v1 requirements covered** ✓

---

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 1 | Core Data Pipeline | Build event log parsing and activity inference engine | REQ-01, REQ-02 | 3 criteria |
| 2 | Pattern System | Implement pattern library and matching logic | REQ-03, REQ-04 | 3 criteria |
| 3 | CLI & Integration | Build CLI interface and output generation | REQ-05, REQ-06 | 3 criteria |

---

## Phase Details

### Phase 1: Core Data Pipeline

**Goal:** Parse UI logs and infer activities from event sequences

**Requirements:** REQ-01, REQ-02

**Success Criteria:**
1. CSV file can be loaded and parsed as event log
2. Events are correctly grouped by logical interpretation with event attributes as supporting evidence
3. Activities are inferred from event groups with mapping to source events

---

### Phase 2: Pattern System

**Goal:** Store patterns and match inferred activities to recommend methods

**Requirements:** REQ-03, REQ-04

**Success Criteria:**
1. Pattern library stores RPA UI interaction patterns with Action, Object, Method, Context structure
2. Inferred activities are matched to patterns considering execution context (web/desktop/visual)
3. Recommended methods are output in correct categories (Extraction/Modification)

---

### Phase 3: CLI & Integration

**Goal:** Provide command-line interface for end-to-end recommendation

**Requirements:** REQ-05, REQ-06

**Success Criteria:**
1. CLI accepts CSV file path as input
2. Output includes inferred activity, recommended method, and event-to-activity mapping
3. Tool runs end-to-end with sample UI log and produces valid recommendations

---

## Traceability

| REQ-ID | Requirement | Phase |
|--------|-------------|-------|
| REQ-01 | Parse UI logs as event logs | Phase 1 |
| REQ-02 | Infer activities from event sequences | Phase 1 |
| REQ-03 | Store and query RPA UI interaction patterns | Phase 2 |
| REQ-04 | Match activities to patterns and recommend methods | Phase 2 |
| REQ-05 | Build CLI interface for running the system | Phase 3 |
| REQ-06 | Generate structured output with activity-method mapping | Phase 3 |

---

*Last updated: 2026-04-15*