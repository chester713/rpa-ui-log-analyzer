---
phase: 05-direct-follow-graph
plan: 01
subsystem: api
tags: [pm4py, dfg, flask, process-mining, testing]
requires:
  - phase: 03-cli-integration
    provides: CLI contract tests and canonical recommendation output shape
  - phase: 04-web-portal
    provides: /analyze and history/result rendering pipeline
provides:
  - Inferred-activity to DFG transformation via PM4Py discover_dfg
  - Additive dfg payload in /analyze response and persisted history entries
  - Regression tests for transformation and additive API/history contract
affects: [05-02-PLAN.md, templates/results.html, web results navigation]
tech-stack:
  added: [pm4py]
  patterns: [session-scoped activity-event log, additive API contract evolution, deterministic payload ordering]
key-files:
  created:
    - src/process_mining/__init__.py
    - src/process_mining/dfg_builder.py
    - tests/test_dfg_transformation.py
    - tests/test_analyze_dfg_contract.py
  modified:
    - app.py
    - requirements.txt
key-decisions:
  - "DFG computation is isolated in src/process_mining/dfg_builder.py and called by app.py as an additive enrichment only."
  - "DFG failures return explicit 500 JSON errors instead of silently persisting incomplete analysis data."
patterns-established:
  - "Transformation isolation: mining logic remains reusable and independently testable from routes."
  - "Contract safety: keep existing recommendation keys intact while adding new top-level payload fields."
requirements-completed: [REQ-13, REQ-15]
duration: 1m 27s
completed: 2026-04-20
---

# Phase 05 Plan 01: Backend DFG Transformation Summary

**Session-scoped inferred-activity sequences now produce deterministic PM4Py direct-follow graphs and are returned/persisted additively as `dfg` without breaking existing recommendation contracts.**

## Performance

- **Duration:** 1m 27s
- **Started:** 2026-04-20T11:16:25+10:00
- **Completed:** 2026-04-20T11:17:52+10:00
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Added a reusable process-mining builder that converts inferred activity mappings into ordered activity-event logs and calls PM4Py `discover_dfg`.
- Integrated DFG payload generation into `/analyze` and persisted history entries with additive `dfg` data.
- Added focused regression tests for DFG transformation correctness and additive analyze/history contract behavior.

## Task Commits

1. **Task 1: Create DFG transformation contract and builder module**
   - `3bc9657` (test): failing DFG transformation tests (RED)
   - `2b8df57` (feat): DFG builder implementation (GREEN)
2. **Task 2: Integrate additive DFG payload into analyze and history paths**
   - `0b85042` (test): failing analyze/history DFG contract tests (RED)
   - `bf93751` (feat): additive DFG integration in response/history (GREEN)

## Files Created/Modified
- `src/process_mining/dfg_builder.py` - PM4Py-backed DFG payload generation with deterministic serialization.
- `src/process_mining/__init__.py` - Process-mining package export for app integration.
- `app.py` - Additive `dfg` enrichment in `/analyze` response/history + explicit DFG error path.
- `requirements.txt` - Added PM4Py dependency.
- `tests/test_dfg_transformation.py` - Transformation correctness tests for edges/start/end and aggregation.
- `tests/test_analyze_dfg_contract.py` - Analyze/history additive contract and recommendation-shape preservation tests.

## Decisions Made
- Kept DFG as a top-level additive payload (`dfg`) to avoid breaking existing consumers of `activities`, `recommendations`, and `history_id`.
- Added explicit DFG generation failure handling (`500` with error details) to avoid silent partial persistence.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Test runner path resolution mismatch on Windows**
- **Found during:** Task 1 verification
- **Issue:** `pytest ...` invocation failed to resolve `src` imports in this environment.
- **Fix:** Used `python -m pytest ...` for all verification commands to preserve module resolution.
- **Files modified:** None (execution adjustment only)
- **Verification:** All listed plan test suites passed with `python -m pytest`.
- **Committed in:** N/A (execution environment handling)

**2. [Rule 3 - Blocking] Import-time dependency failure before integration point**
- **Found during:** Task 1 GREEN implementation
- **Issue:** Importing `pm4py`/`pandas` at module load blocked tests before dependency installation.
- **Fix:** Deferred `discover_dfg` import to runtime and added a minimal in-test dataframe fallback used only when pandas is unavailable.
- **Files modified:** `src/process_mining/dfg_builder.py`
- **Verification:** `python -m pytest tests/test_dfg_transformation.py -q` passed.
- **Committed in:** `2b8df57`

---

**Total deviations:** 2 auto-fixed (Rule 3: 2)
**Impact on plan:** Both were execution-blocking fixes needed to complete planned work with no functional scope creep.

## Issues Encountered
- None beyond the two blocking issues auto-fixed above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Backend now provides stable `entry.dfg` payload shape for web rendering.
- Plan 05-02 can consume `entry.dfg` directly for full-width graph rendering and bidirectional highlight wiring.

## Self-Check: PASSED
- FOUND: `.planning/phases/05-direct-follow-graph/05-direct-follow-graph-01-SUMMARY.md`
- FOUND: `3bc9657`
- FOUND: `2b8df57`
- FOUND: `0b85042`
- FOUND: `bf93751`
