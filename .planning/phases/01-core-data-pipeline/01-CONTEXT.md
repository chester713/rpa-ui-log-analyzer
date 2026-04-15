# Phase 1: Core Data Pipeline - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning
**Source:** Key design decisions from discussion

<domain>
## Phase Boundary

This phase delivers the core data pipeline:
- CSV parsing engine (event log format)
- Event grouping logic
- LLM-powered activity inference engine
- Event-to-activity mapping with confidence scores

</domain>

<decisions>
## Implementation Decisions

### CSV Parsing
- **Required column:** `event` (fails if missing)
- **Optional columns:** All other columns treated as event attributes/context
- **Format:** Abb & Rehse reference model (Process Mining style)

### Event Grouping
- **Strategy:** Consecutive events + shared attributes
- **Grouping criteria:** Same app, webpage, or element
- **Output:** Event groups with shared context

### Activity Inference
- **Approach:** LLM-powered logical interpretation
- **Vocabulary:** Map to AOMC (Action-Object-Method-Context) from pattern proposal PDF
- **Mapping:** One-to-many (multiple events → one activity) and one-to-one (single event → single activity)

### Mapping Structure
- **Confidence score:** Numeric score for inference certainty
- **Attribute breakdown:** Event attributes used as supporting evidence

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Scope
- `.planning/PROJECT.md` — Project definition and success criteria
- `.planning/REQUIREMENTS.md` — REQ-01 and REQ-02 specifics
- `.planning/ROADMAP.md` — Phase 1 goal and success criteria

</canonical_refs>

<specifics>
## Specific Ideas

- Event log parsing similar to Process Mining (Abb & Rehse model)
- LLM inference with confidence scoring
- AOMC vocabulary mapping from pattern proposal PDF
- Output must include: inferred activity, recommended method (later phases), event-to-activity mapping

</specifics>

<deferred>
## Deferred Ideas

- Pattern library population (Phase 2)
- CLI interface (Phase 3)
- Multiple format support (REQ-07, v2)

</deferred>

---

*Phase: 01-core-data-pipeline*
*Context gathered: 2026-04-15 from user discussion*
