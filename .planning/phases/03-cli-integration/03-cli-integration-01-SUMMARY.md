---
phase: 03-cli-integration
plan: 01
subsystem: testing
tags: [cli, pytest, json-contract, regression]
requires:
  - phase: 01-core-data-pipeline
    provides: parser and inference pipeline consumed by CLI
  - phase: 02-pattern-system
    provides: method recommendation model and matching output
provides:
  - Black-box CLI regression tests for help, missing file, and JSON output
  - Deterministic CSV fixture for CLI contract verification
  - Enforced recommendation serialization key contract for REQ-06 consumers
affects: [phase-04-web-portal, cli-consumers, downstream-json-parsers]
tech-stack:
  added: []
  patterns: [subprocess-driven CLI contract testing, canonical to_dict output shape]
key-files:
  created:
    - tests/test_cli.py
    - tests/fixtures/cli_sample.csv
    - .planning/phases/03-cli-integration/03-cli-integration-01-SUMMARY.md
  modified:
    - src/models/pattern.py
key-decisions:
  - "Use black-box subprocess tests against src_cli.py instead of mocking internals to lock true CLI behavior."
  - "Preserve one canonical recommendation JSON schema with stable key presence for REQ-06 traceability."
patterns-established:
  - "CLI contract tests must assert exit codes, stderr behavior, and serialized JSON shape."
  - "Recommendation serialization remains the canonical integration boundary for downstream consumers."
requirements-completed: [REQ-05, REQ-06]
duration: 2m 12s
completed: 2026-04-20
---

# Phase 3 Plan 01: CLI Contract Hardening Summary

**CLI contract regression coverage now validates real entrypoint behavior and deterministic JSON recommendation records for REQ-05/REQ-06.**

## Performance

- **Duration:** 2m 12s
- **Started:** 2026-04-20T00:50:31Z
- **Completed:** 2026-04-20T00:52:42Z
- **Tasks:** 3
- **Files modified:** 3 (task scope)

## Accomplishments
- Added end-to-end CLI regression tests for `--help`, missing file errors, and `--output` JSON contract generation.
- Added a deterministic CLI fixture CSV (`click`, `type`, `submit`) to support reproducible contract verification.
- Hardened recommendation serialization contract by formalizing canonical output record shape and verifying required keys via CLI-generated JSON.
- Verified regression safety by running CLI, parser, and inference test suites.

## Task Commits

1. **Task 1: Create CLI contract regression tests and fixture** - `9d2140e` (test)
2. **Task 2: Harden output serialization contract for recommendations and pipeline** - `0bce16c` (feat)
3. **Task 3: Run full phase verification for CLI and existing core tests** - `f2f7978` (test)

## Files Created/Modified
- `tests/test_cli.py` - Black-box CLI regression tests for help/error/success and JSON output schema keys.
- `tests/fixtures/cli_sample.csv` - Sample UI event log fixture used by CLI integration tests.
- `src/models/pattern.py` - Canonical recommendation dictionary contract explicitly retained for stable key presence.

## Decisions Made
- Use subprocess-based CLI testing as the long-term contract harness for CLI regressions.
- Keep canonical output key names unchanged while enforcing deterministic key presence for recommendation records.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 3 CLI/output requirements now have deterministic automated verification coverage.
- Downstream phases can rely on stable CLI JSON contract and regression guardrails.

## Self-Check: PASSED

- FOUND: `.planning/phases/03-cli-integration/03-cli-integration-01-SUMMARY.md`
- FOUND commits: `9d2140e`, `0bce16c`, `f2f7978`
