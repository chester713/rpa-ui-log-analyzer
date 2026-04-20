# REQUIREMENTS.md

## v1 Requirements

### Event Log Processing

- [ ] **REQ-01**: Parse UI logs (CSV format) as event logs similar to Process Mining event logs
  - Handle required event/activity column
  - Handle event attributes (context information about the event)

- [ ] **REQ-02**: Infer activities from event sequences
  - Apply logical interpretation to determine activities
  - Use event attributes as supporting evidence for grouping decisions
  - Support one-to-many: multiple events → one activity
  - Support one-to-one: single event → single activity

### Pattern System

- [ ] **REQ-03**: Store RPA UI interaction patterns
  - Maintain pattern library with Action + Object + Method + Context structure
  - Support querying patterns by activity and context

- [ ] **REQ-04**: Match inferred activities to patterns and recommend methods
  - Match activities against pattern definitions
  - Consider execution context (web environment, desktop environment, visual environment)
  - Output applicable method (Extraction or Modification category)

### CLI & Output

- [x] **REQ-05**: Build CLI interface
  - Accept CSV file path as input
  - Provide usage instructions and help

- [x] **REQ-06**: Generate structured output
  - Output inferred activity per event group
  - Output recommended method
  - Include event-to-activity mapping for traceability

---

## v2 Requirements

- [ ] **REQ-07**: Support multiple event log formats (JSON, XES)
- [ ] **REQ-08**: Add confidence scores for activity inference
- [ ] **REQ-09**: Provide pattern explanation in output

### v2 - Future Enhancements

- [ ] **REQ-10**: Web portal for UI log upload
  - Browser-based interface for file upload
  - Display recommendations in web UI

- [ ] **REQ-11**: Replaceable LLM
  - Configurable LLM provider for activity inference
  - Support user-provided API keys

- [ ] **REQ-12**: Skill-based pattern system
  - Patterns stored as skill.md files
  - Recommendation approach as separate skill.md

## Out of Scope

- **GUI interface** — CLI-only for v1
- **Real-time log monitoring** — Batch processing only
- **Bot generation** — Recommendations only, no execution
- **RPA platform integration** — Standalone tool

---

## Traceability

| REQ-ID | Phase | Description |
|--------|-------|-------------|
| REQ-01 | Phase 1 | Event log parser |
| REQ-02 | Phase 1 | Activity inference engine |
| REQ-03 | Phase 2 | Pattern library |
| REQ-04 | Phase 2 | Pattern matching and method recommendation |
| REQ-05 | Phase 3 | CLI interface |
| REQ-06 | Phase 3 | Structured output generation |

---

*Last updated: 2026-04-15*