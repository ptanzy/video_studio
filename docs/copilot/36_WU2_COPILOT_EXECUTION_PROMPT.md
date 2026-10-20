# 36 — WU2 Copilot handoff

## First message to Copilot (Plan/inspection, no implementation)
Read `AGENTS.md`, docs 32–35, the relevant earlier job/render specifications (05, 11, 12, 14, 21, 30), and the actual WU1 Python source, tests, contracts and CI. Do not change files. Report (1) proposed WU2 files/interfaces, (2) how existing WU1 atomic storage/errors/ports will be reused, (3) any concrete conflicts or blocking decisions, (4) exact implementation slices and tests, and (5) any discrepancy between checked-in repo and v1.9 handoff. Do not implement or modify `legacy_v2`. Do not invent missing product decisions.

## Implementation authorization message (send after reviewing the plan)
Implement WU2 strictly according to `docs/copilot/34_WU2_MEDIA_INFRASTRUCTURE_BASELINE.md` and `35_WU2_TEST_MATRIX_AND_FAILURE_SEMANTICS.md`, respecting the actual WU1 code and `AGENTS.md`. Work in small testable slices: (1) contracts/domain/ports, (2) repository/snapshot/idempotency, (3) probe/process adapters, (4) worker/recovery/cancellation, (5) synthetic media integration and CI. Run and report tests after each slice. No UI, API, full compilation, Shorts, effects, uploads, or `legacy_v2` edits. Do not commit, merge or start WU3. Stop for independent review with exact changed files, tests, limitations and deferred decisions.

## Important: approval
These are templates, not automatic authorization. WU2 is authorized only when the user explicitly instructs Copilot to implement it.
