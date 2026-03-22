# TYS

This file defines the minimum operating rules for the multi-stage pipeline.

## Core flow

1. Divergence (Auralis): expand and clarify intent.
2. Convergence (Krax): choose and constrain a concrete implementation direction.
3. Decomposition (Mason): convert the plan into executable tasks.
4. Execution (Flash): perform task implementation only.
5. Reality check (Vera): validate against observable behavior.
6. Feedback: route validated findings back to Auralis.

## Stage invariants

- Auralis: may add clarity, goals, and constraints; must not emit execution steps.
- Krax: may refine and choose strategy; must not redefine product intent.
- Mason: may decompose work; must not redesign architecture.
- Flash: may execute tasks; must not reinterpret task intent.
- Vera: may observe and report evidence; must not rewrite plans.

If a stage violates role boundaries, the run fails closed and the next stage must not start.

## Required artifacts per run

- `plan_v1.json` from Auralis
- `plan_v2.json` from Krax
- `tasks.json` from Mason/Flash
- `run_trace.json` timeline across stages
- `gatekeeper_decision.json` before production promotion

Schema files are defined in `contracts/runtime_artifacts/*.schema.json`.

## Gatekeeper policy

Promotion is allowed only when all checks below pass:

1. Contract check: required artifacts exist and validate.
2. Regression check: no known critical behavior regresses.
3. Reality check: Vera evidence is present and consistent with acceptance criteria.

If any check fails, mark `approved=false` and return feedback to Auralis.

## Feedback routing

Feedback must return to Auralis first, not directly to Mason.

1. Vera writes evidence + failure reasons.
2. Auralis synthesizes updated meaning/intent.
3. A new `plan_v1.json` is created for the next loop.

## Safety rules

- One improvement change per run.
- Every run must be reversible.
- No direct self-modification in production without gatekeeper approval.
