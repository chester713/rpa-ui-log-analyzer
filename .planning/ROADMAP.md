# ROADMAP.md

## Project: RPA UI Log Analyzer

**Phases:** 4 | **Requirements:** 6 + v2 | **v1 complete** ✓

---

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 1 | Core Data Pipeline | Build event log parsing and activity inference engine | REQ-01, REQ-02 | 3 criteria |
| 2 | Pattern System | Implement pattern library and matching logic | REQ-03, REQ-04 | 3 criteria |
| 3 | CLI & Integration | Build CLI interface and output generation | REQ-05, REQ-06 | 3 criteria |
| 4 | Web Portal | Browser-based UI for file upload and recommendations | REQ-10, REQ-11 | 3 criteria |

---

### Phase 4: Web Portal

**Goal:** Browser-based UI for file upload and recommendations display

**Requirements:** REQ-10 (Web portal), REQ-11 (Replaceable LLM), REQ-12 (Skill-based patterns)

**Success Criteria:**
1. User can upload CSV files through web interface
2. Recommendations displayed in web UI with activity-method mapping
3. LLM configuration available in settings panel

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
| REQ-07 | (v2) Support multiple event log formats | - |
| REQ-08 | (v2) Add confidence scores for activity inference | - |
| REQ-09 | (v2) Provide pattern explanation in output | - |
| REQ-10 | (v2) Web portal for UI log upload | - |
| REQ-11 | (v2) Replaceable LLM | - |
| REQ-12 | (v2) Skill-based pattern system | -

---

*Last updated: 2026-04-15*

## v1 Complete ✓

All 3 phases completed:
- Phase 1: Core Data Pipeline ✓
- Phase 2: Pattern System ✓
- Phase 3: CLI & Integration ✓