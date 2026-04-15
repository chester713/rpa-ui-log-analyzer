# Phase 2: Pattern System - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning
**Source:** Key design decisions from discussion

<domain>
## Phase Boundary

This phase delivers:
- Pattern library with 13 RPA UI interaction patterns (one skill.md per pattern)
- Pattern matching logic (exact match on Activity = Action + Object in AOMC)
- Method recommendation based on pattern match + execution context
- Output: Inferred Activity → Events → Execution Environment → Pattern Matched → Method

</domain>

<decisions>
## Implementation Decisions

### Pattern Storage
- **Structure:** One skill.md per pattern (13 patterns total)
- **Location:** Pattern definitions stored as skill files
- **Content:** Each pattern includes Action, Object, Method, Context

### Pattern Matching
- **Algorithm:** Exact match - Activity (Action + Object in AOMC) → Pattern name
- **Input:** Inferred activity from Phase 1 (AOMC structured)
- **Output:** Pattern name that matches the activity's Action + Object

### Context Weighting
- **Context determines variant:** Same Action+Object maps to different pattern based on environment
- **Examples:**
  - web → "activate html element"
  - desktop → "activate ui element"
- **Context sources:** Event attributes (app, webpage, element metadata)

### Output Structure
- **Flow:** Inferred activity → Events → Execution environment → Pattern matched → Method
- **Categories:** Extraction or Modification

### REQ-03 (Pattern Storage)
- Pattern library with Action + Object + Method + Context structure
- Query patterns by activity and context

### REQ-04 (Pattern Matching)
- Match activities against pattern definitions
- Consider execution context (web/desktop/visual)
- Output applicable method (Extraction or Modification category)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Scope
- `.planning/PROJECT.md` — Project definition
- `.planning/REQUIREMENTS.md` — REQ-03 and REQ-04 specifics
- `.planning/ROADMAP.md` — Phase 2 goal and success criteria

### Phase 1 Output
- `.planning/phases/01-core-data-pipeline/01-CONTEXT.md` — Activity inference structure (AOMC)
- Activity model outputs: Action, Object, Method, Context

</canonical_refs>

<specifics>
## Specific Ideas

- 13 patterns based on user-provided RPA UI interaction definitions
- skill.md format for pattern storage (extensible, machine-readable)
- Exact matching on Action+Object from AOMC output
- Context variants: web, desktop, visual environments

</specifics>

<deferred>
## Deferred Ideas

- REQ-07: Multiple event log formats (v2)
- REQ-08: Confidence scores for pattern matching
- REQ-09: Pattern explanation in output

</deferred>

---

*Phase: 02-pattern-system*
*Context gathered: 2026-04-15 from user discussion*