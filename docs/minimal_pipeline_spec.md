# Minimal Pipeline Spec

This document defines the smallest enforceable spec for staged execution and feedback.

## Runtime paths

For a job id `<job_id>`, place artifacts in `runs/<job_id>/` (or `archive/<job_id>/` after completion).

- `runs/<job_id>/plan_v1.json`
- `runs/<job_id>/plan_v2.json`
- `runs/<job_id>/tasks.json`
- `runs/<job_id>/run_trace.json`
- `runs/<job_id>/gatekeeper_decision.json`

## Artifact contracts

Use these schemas:

- `contracts/runtime_artifacts/plan_v1.schema.json`
- `contracts/runtime_artifacts/plan_v2.schema.json`
- `contracts/runtime_artifacts/tasks.schema.json`
- `contracts/runtime_artifacts/run_trace.schema.json`
- `contracts/runtime_artifacts/gatekeeper_decision.schema.json`

## Minimal run checks

A run is considered coherent only if all checks pass:

1. Stage role check: each stage output matches its role boundary.
2. Contract check: all required artifacts exist and validate.
3. Causality check: `run_trace.json` events are ordered and complete.
4. Reality check: Vera result exists and links to observable evidence.

## Promotion rule

`gatekeeper_decision.json` must contain:

- `approved=true`
- all checks present with `passed=true`
- explicit reason string

Otherwise the run is not promotable and feedback returns to Auralis for a new `plan_v1`.

## Non-goals

This spec does not prescribe model choice, UI framework, or deployment topology.
It only defines stage boundaries, artifact contracts, and promotion policy.
