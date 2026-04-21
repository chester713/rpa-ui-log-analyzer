# ROADMAP.md

## Project: RPA UI Log Analyzer

**Phases:** 6 | **Requirements:** 6 + v2 | **v1 complete** ✓

---

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 1 | Core Data Pipeline | Build event log parsing and activity inference engine | REQ-01, REQ-02 | 3 criteria |
| 2 | Pattern System | Implement pattern library and matching logic | REQ-03, REQ-04 | 3 criteria |
| 3 | CLI & Integration | Build CLI interface and output generation | REQ-05, REQ-06 | 3 criteria |
| 4 | Web Portal | Browser-based UI for file upload and recommendations | REQ-10, REQ-11 | 3 criteria |
| 5 | Direct-Follow Graph | Generate and visualize DFG from inferred activities in web portal | REQ-13, REQ-14, REQ-15 | 4 criteria |
| 6 | Transparent Analysis Workflow | Build hybrid progressive-disclosure architecture and pipeline artifact contracts for transparent analysis workspace | REQ-16, REQ-17, REQ-18 | 4 criteria |

---

### Phase 4: Web Portal

**Goal:** Browser-based UI for file upload and recommendations display

**Requirements:** REQ-10 (Web portal), REQ-11 (Replaceable LLM), REQ-12 (Skill-based patterns)

**Success Criteria:**
1. User can upload CSV files through web interface
2. Recommendations displayed in web UI with activity-method mapping
3. LLM configuration available in settings panel

---

### Phase 5: Direct-Follow Graph

**Goal:** Generate process-mining direct-follow graph from inferred activities and provide interactive graph-event navigation in web results UI

**Requirements:** REQ-13, REQ-14, REQ-15

**Plans:** 2 plans

Plans:
- [ ] 05-01-PLAN.md — Build activity-log→DFG backend transformation with additive API/history contract and tests
- [ ] 05-02-PLAN.md — Render full-width interactive DFG in results UI with bidirectional event/node highlighting tests

**Success Criteria:**
1. Activity event log is built from inferred activities with per-session order preserved
2. DFG edges/start/end are produced using existing process-mining direct-follows library
3. Results page renders DFG below current two panels at full content width
4. Node↔event click highlighting works bidirectionally without breaking existing recommendations flow

---

### Phase 6: Transparent Analysis Workflow

**Goal:** Establish hybrid progressive-disclosure workflow foundations and backend/state artifact contracts that expose intermediate analysis stages without breaking existing outputs.

**Requirements:** REQ-16, REQ-17, REQ-18

**Plans:** 1 plans

Plans:
- [x] 06-01-PLAN.md — Define progressive stage contracts, artifactize pipeline states, and add welcome/workspace flow foundations with backward-compatibility tests

**Success Criteria:**
1. Welcome-first entry flow exists before upload, while upload and event-column selection behavior remains unchanged
2. Analyze/history contracts include explicit artifacts + logic explanations for all six progressive stages
3. Hybrid progressive-disclosure workspace state contract supports section-by-section reveal without requiring full page wizard navigation
4. Existing final outputs (recommendations, DFG, export behavior) remain regression-safe and backward compatible

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

**Plans:** 1 plan

Plans:
- [x] 03-01-PLAN.md — Harden CLI/output contracts and add Phase 3 regression tests

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
| REQ-13 | (v2) Build direct-follow graph from inferred activities | Phase 5 |
| REQ-14 | (v2) Interactive DFG visualization linked with event panel | Phase 5 |
| REQ-15 | (v2) Regression-safe DFG integration with tests | Phase 5 |
| REQ-16 | (v2) Hybrid progressive-disclosure workflow | Phase 6 |
| REQ-17 | (v2) Pipeline artifactization and transparency contracts | Phase 6 |
| REQ-18 | (v2) Preserve final outputs while adding transparency | Phase 6 |

---

*Last updated: 2026-04-15*

## v1 Complete ✓

All 3 phases completed:
- Phase 1: Core Data Pipeline ✓
- Phase 2: Pattern System ✓
- Phase 3: CLI & Integration ✓
