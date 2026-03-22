# Sprint Board A/B/C

This board converts the abstract-to-concrete pipeline plan into three execution sprints with explicit deliverables, owners, artifacts, and acceptance gates.

## Scope

Pipeline:

You -> Auralis -> Plan v1 -> Krax/Grok -> Plan v2 -> Mason -> Flash -> Vera -> Feedback

Primary goal:

Move from theoretical flow to repeatable, testable production behavior with stage isolation and measurable outcomes.

## Ownership map

- Auralis owner: intent shaping, constraints, acceptance checks
- Krax owner: implementation strategy refinement and constrained handoff
- Mason owner: task decomposition and sprint packaging
- Flash owner: execution and implementation evidence
- Vera owner: validation and evidence-driven verdicts
- Gatekeeper owner: promotion decision and run-level approval

## Sprint A - Contract and artifact baseline

Goal

Lock down stage boundaries and guarantee artifact completeness for every run.

Deliverables

1. Runtime artifact contract enforcement for:
- `plan_v1.json`
- `plan_v2.json`
- `tasks.json`
- `run_trace.json`
- `gatekeeper_decision.json`

2. Artifact validator command integrated into run flow.

3. Run trace writer at each stage handoff.

4. Basic failure taxonomy for non-compliant runs.

Owner mapping

- Auralis: `plan_v1` shape and acceptance-check requirements
- Krax: `plan_v2` shape and `changes_from_v1` quality
- Mason: `tasks` decomposition structure
- Flash: task execution record format
- Vera: verdict evidence linkage requirements
- Gatekeeper: baseline required checks list

Required artifacts

- `runs/<job_id>/plan_v1.json`
- `runs/<job_id>/plan_v2.json`
- `runs/<job_id>/tasks.json`
- `runs/<job_id>/run_trace.json`
- `runs/<job_id>/gatekeeper_decision.json`

Acceptance criteria

1. Two consecutive runs produce all required artifacts.
2. Artifact contracts validate for all required fields.
3. Stage role violations fail closed and are traceable.

Exit gate

- `gatekeeper_decision.json` includes contract check results with explicit pass/fail.

## Sprint B - Decomposition and execution reliability

Goal

Make Plan v2 to task decomposition and Flash execution predictable and auditable.

Deliverables

1. Mason quality checks:
- each task has owner
- each task has done criteria
- task dependency ordering is valid

2. Sprint slicer output (A/B/C scoped tasks with bounded size).

3. Flash execution manifest:
- commands run
- files changed
- validation outputs

4. Regression smoke suite for core path.

Owner mapping

- Mason: decomposition checks and sprint slicing rules
- Flash: execution manifest and task-level validation
- Krax: ensure Plan v2 supports deterministic decomposition
- Vera: smoke result verification and evidence capture
- Gatekeeper: regression and coherence gates

Required artifacts

- `runs/<job_id>/tasks.json`
- `runs/<job_id>/execution_manifest.json`
- `runs/<job_id>/vera.json` (or equivalent verdict)
- `runs/<job_id>/gatekeeper_decision.json`

Acceptance criteria

1. 90% of tasks execute without reinterpretation requests.
2. Every completed task has at least one verification output.
3. Regression smoke path remains green across two runs.

Exit gate

- `gatekeeper_decision.json` must contain regression and coherence check pass entries.

## Sprint C - Validation loop and controlled promotion

Goal

Operationalize reality-first validation and safe promotion with feedback routed to Auralis.

Deliverables

1. Vera evidence bundle standardization:
- screenshots/logs linked to verdict
- explicit pass/fail reason

2. Gatekeeper decision policy enforcement:
- promotion only with all checks passed
- explicit reason and check list

3. Feedback-loop writer:
- Vera findings converted into next-cycle Auralis input
- new `plan_v1` generated from validated feedback

4. Improvement-inbox pilot (one change per run).

Owner mapping

- Vera: evidence + verdict quality
- Gatekeeper: approval policy and audit trail
- Auralis: feedback synthesis into revised intent
- Krax/Mason/Flash: execute revised plan without role drift

Required artifacts

- `runs/<job_id>/vera.json`
- `runs/<job_id>/gatekeeper_decision.json`
- `runs/<job_id>/feedback_summary.json`
- `runs/<job_id>/plan_v1_next.json` (or next run `plan_v1.json`)

Acceptance criteria

1. No promotion occurs without `approved=true` and full check coverage.
2. Every fail includes machine-readable reason + linked evidence.
3. One complete feedback cycle produces a revised plan and rerun.

Exit gate

- At least one full loop validated:
  intent -> plan v1 -> plan v2 -> tasks -> execution -> validation -> feedback -> revised plan.

## Board tracking template

Use this status model for each sprint item:

- `not-started`
- `in-progress`
- `blocked`
- `done`

Use this issue naming convention:

- `A-<n>` for Sprint A items
- `B-<n>` for Sprint B items
- `C-<n>` for Sprint C items

## Initial board items

Sprint A

- `A-1` Contract validator wiring
- `A-2` Run trace writer at handoffs
- `A-3` Stage role violation fail-closed policy
- `A-4` Gatekeeper contract baseline checks

Sprint B

- `B-1` Mason decomposition quality checks
- `B-2` Sprint slicer output format
- `B-3` Flash execution manifest
- `B-4` Regression smoke suite integration

Sprint C

- `C-1` Vera evidence bundle standard
- `C-2` Gatekeeper promotion enforcement
- `C-3` Feedback synthesis into revised `plan_v1`
- `C-4` One-change-per-run improvement pilot

## Definition of done (global)

A sprint item is done only when:

1. Required artifact files exist.
2. Schema and quality checks pass.
3. Evidence links are present.
4. Run trace includes the item event.
5. Gatekeeper check status is recorded.
