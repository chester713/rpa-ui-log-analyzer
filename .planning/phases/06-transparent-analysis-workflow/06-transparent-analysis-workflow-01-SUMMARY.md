---
phase: 06-transparent-analysis-workflow
plan: 01
subsystem: ui
tags: [flask, jinja2, progressive-disclosure, contract-tests]
requires:
  - phase: 05-direct-follow-graph
    provides: additive analyze/history DFG contract and results-page DFG wiring
provides:
  - Welcome-first route with dedicated /upload entry preserving existing upload behavior
  - Additive six-stage progressive_artifacts/progressive_logic contracts in analyze response and persisted history
  - Guided /workspace/<history_id> scaffold with deterministic six-stage replay from persisted contracts
affects: [web-ui, analysis-contract, history-replay, regression-tests]
tech-stack:
  added: []
  patterns: [additive contract evolution, deterministic stage key ordering, textContent-based rendering]
key-files:
  created:
    - templates/welcome.html
    - templates/workspace.html
    - tests/test_analyze_progressive_contract.py
    - tests/test_workspace_progressive_wiring.py
  modified:
    - app.py
    - templates/index.html
    - templates/columns.html
    - templates/history.html
    - templates/settings.html
    - templates/results.html
key-decisions:
  - "Kept /analyze and history contracts additive-only by introducing progressive_artifacts/progressive_logic without renaming existing keys."
  - "Introduced /upload as the upload landing route while moving / to welcome-first entry and updating nav links across templates."
  - "Rendered workspace artifact/logic content via textContent + Jinja tojson to preserve safe escaping at the history->UI trust boundary."
patterns-established:
  - "Progressive stage contracts are stored in deterministic PROGRESSIVE_STAGE_KEYS order for stable replay."
  - "Workspace route normalizes missing progressive data for backward compatibility with older history entries."
requirements-completed: [REQ-16, REQ-17, REQ-18]
duration: 603m 17s
completed: 2026-04-21
---

# Phase 6 Plan 1: Transparent Analysis Workflow Summary

**Welcome-first navigation plus deterministic six-stage transparency contracts now power a guided workspace while preserving existing analyze/DFG/export behaviors.**

## Performance

- **Duration:** 603m 17s
- **Started:** 2026-04-21T10:52:26Z
- **Completed:** 2026-04-21T12:29:30Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments
- Added `progressive_artifacts` + `progressive_logic` to `/analyze` response and persisted history with fixed six-stage ordering.
- Added welcome-first UX (`/`) with dedicated `/upload` entry while preserving existing upload and column-selection contracts.
- Added `/workspace/<history_id>` and a six-section progressive workspace scaffold that replays persisted artifacts/logic safely.
- Preserved and re-verified existing final-output behaviors (results route, DFG payload/UI wiring, export flow, CLI/parser/inference regressions).

## Task Commits

1. **Task 1: Define and test progressive artifact state contract for six analysis stages**
   - `f3aea79` test(06-01): add progressive artifact contract tests for analyze/history
   - `ba7fc06` feat(06-01): add six-stage progressive artifacts to analyze and history
2. **Task 2: Add welcome-first entry and preserve upload/column-selection behavior**
   - `32b8965` test(06-01): add welcome-first and upload routing contract tests
   - `04104a7` feat(06-01): introduce welcome-first route while keeping upload flow intact
3. **Task 3: Create guided analysis workspace foundation with progressive stepper sections**
   - `ace1e48` test(06-01): add workspace progressive wiring contract tests
   - `74de8f6` feat(06-01): add guided workspace route and six-stage scaffold

## Files Created/Modified
- `app.py` - Added stage key constants, progressive contract builder, welcome/upload/workspace routes, and additive response/history persistence.
- `templates/welcome.html` - New welcome-first landing page with continue action to upload flow.
- `templates/workspace.html` - New six-stage stepper workspace rendering persisted artifacts and logic explanations.
- `templates/index.html` - Upload page nav updated for welcome-first flow and explicit detect-column URL marker for wiring contract tests.
- `templates/columns.html` - Navigation and cancel route updated to `/upload`.
- `templates/history.html` - Navigation and empty-state upload CTA updated to `/upload`.
- `templates/settings.html` - Navigation updated for welcome-first flow.
- `templates/results.html` - Navigation updated while retaining DFG + export contract wiring.
- `tests/test_analyze_progressive_contract.py` - New regression tests for additive progressive analyze/history contract.
- `tests/test_workspace_progressive_wiring.py` - New routing/template wiring tests for welcome/upload/workspace and results compatibility.

## Decisions Made
- Used additive-only contract evolution for transparency (`progressive_artifacts`, `progressive_logic`) to preserve existing consumers.
- Kept existing upload/column selection mechanics by introducing `/upload` instead of refactoring current upload template behavior.
- Ensured workspace stage rendering uses escaped JSON + `textContent` (no `innerHTML`) per threat mitigation for persisted artifact text.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed deterministic stage-order contract in JSON responses**
- **Found during:** Task 1 verification
- **Issue:** Flask JSON provider sorted response keys alphabetically, breaking required fixed stage order contract.
- **Fix:** Explicitly disabled JSON key sorting (`app.config["JSON_SORT_KEYS"] = False`, `app.json.sort_keys = False`) and preserved ordered stage dictionaries.
- **Files modified:** `app.py`
- **Verification:** `python -m pytest tests/test_analyze_progressive_contract.py tests/test_analyze_dfg_contract.py -q`
- **Committed in:** `ba7fc06`

---

**Total deviations:** 1 auto-fixed (Rule 1 bug)
**Impact on plan:** Required for correctness of the plan’s deterministic progressive contract; no scope creep.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Transparent workflow foundation is in place with persisted stage contracts and replayable workspace.
- Existing DFG/results/export and core CLI/parser/inference flows remain regression-safe.

## Self-Check: PASSED

- FOUND: `.planning/phases/06-transparent-analysis-workflow/06-transparent-analysis-workflow-01-SUMMARY.md`
- FOUND commits: `f3aea79`, `ba7fc06`, `32b8965`, `04104a7`, `ace1e48`, `74de8f6`
