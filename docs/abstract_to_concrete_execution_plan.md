# Abstract-to-Concrete Execution Plan

## Purpose

Define a long-form, executable roadmap for the multi-agent chain:

Human Intent -> Auralis -> Plan v1 -> Krax/Grok -> Plan v2 -> Mason -> Flash -> Vera -> Feedback to Auralis

This plan is intentionally practical: each phase has deliverables, runtime artifacts, acceptance criteria, and rollback rules.

## Guiding principles

1. Role isolation
- Each stage transforms only within its role.
- No stage may reinterpret upstream intent outside contract.

2. Artifact-first flow
- Every stage output is a file artifact with schema.
- Downstream stages consume artifacts, not chat memory.

3. Reality over narrative
- Vera evidence and checks decide pass/fail.
- Promotion requires objective checks, not confidence alone.

4. Slow self-improvement
- One meaningful system change per loop.
- Every promotion reversible.

## Stage contract summary

## Auralis (Explore, refine intent)

Inputs
- Human goal
- Prior run feedback

Outputs
- `plan_v1.json`

Allowed
- Clarify objective, constraints, success criteria.

Forbidden
- Implementation decomposition and code-level commitments.

Success criteria
- `plan_v1.json` validates against schema.
- At least one measurable acceptance check exists.

## Krax + Grok (Refine, constrain)

Inputs
- `plan_v1.json`

Outputs
- `plan_v2.json`

Allowed
- Select strategy, constrain scope, identify risks and trade-offs.

Forbidden
- Changing product intent or deleting acceptance checks.

Success criteria
- `plan_v2.json` validates.
- `changes_from_v1` is explicit and auditable.

## Mason (Break into tasks + sprints)

Inputs
- `plan_v2.json`

Outputs
- `tasks.json`
- optional sprint slices (`sprint_01.json`, etc.)

Allowed
- Decompose into ordered tasks with clear done criteria.

Forbidden
- Redesigning architecture or intent.

Success criteria
- Every task has owner and done criteria.
- Task order forms a coherent dependency chain.

## Flash (Execute)

Inputs
- `tasks.json`

Outputs
- code changes
- execution logs
- command/result manifest

Allowed
- Implement exactly scoped tasks.

Forbidden
- Rewriting objectives without feedback loop.

Success criteria
- Task done criteria satisfied.
- Build/test checks pass at required scope.

## Vera (Validate)

Inputs
- runtime target and acceptance criteria
- expected behavior from upstream artifacts

Outputs
- evidence bundle (screenshots, logs)
- verdict artifact (`vera.json` or equivalent)

Allowed
- Observe, test, and report reality.

Forbidden
- Redefining what success means.

Success criteria
- Evidence is reproducible and linked.
- Verdict is explicit pass/fail with rationale.

## Feedback routing

Inputs
- Vera verdict + evidence
- gatekeeper result

Outputs
- next `plan_v1.json`

Rule
- Feedback always returns to Auralis first.

## Runtime artifact model

Required per run id `<job_id>`:

- `runs/<job_id>/plan_v1.json`
- `runs/<job_id>/plan_v2.json`
- `runs/<job_id>/tasks.json`
- `runs/<job_id>/run_trace.json`
- `runs/<job_id>/gatekeeper_decision.json`

Schema references:

- `contracts/runtime_artifacts/plan_v1.schema.json`
- `contracts/runtime_artifacts/plan_v2.schema.json`
- `contracts/runtime_artifacts/tasks.schema.json`
- `contracts/runtime_artifacts/run_trace.schema.json`
- `contracts/runtime_artifacts/gatekeeper_decision.schema.json`

## Long-form rollout plan

## Phase 0 - Baseline and controls

Objectives
- Freeze role boundaries and artifact contracts.
- Ensure all current runs produce stable trace logs.

Deliverables
- Contract docs finalized.
- JSON schemas in place.
- Basic validator command for artifacts.

Acceptance
- Two consecutive runs produce complete artifact sets.
- No stage writes out-of-role fields.

Rollback
- Disable promotion path and keep sandbox-only mode.

## Phase 1 - Plan v1 and Plan v2 reliability

Objectives
- Make intent refinement deterministic and auditable.

Deliverables
- Stable generation prompts/templates for Plan v1 and Plan v2.
- Diff report between v1 and v2 for each run.

Acceptance
- Every run includes explicit v1->v2 change log.
- Acceptance checks survive unchanged unless explicitly justified.

Rollback
- Revert to last known stable prompt templates.

## Phase 2 - Decomposition quality (Mason)

Objectives
- Ensure tasks are executable, bounded, and dependency-aware.

Deliverables
- Task quality checks (owner exists, done criteria exists, dependency order valid).
- Sprint slicing rules (size and scope thresholds).

Acceptance
- 90%+ tasks complete without reinterpretation requests.
- Reduced mid-execution scope drift.

Rollback
- Fallback to manual task curation for complex runs.

## Phase 3 - Execution discipline (Flash)

Objectives
- Convert tasks into reliable implementation throughput.

Deliverables
- Command/result manifest per task.
- Required validation set by task type (syntax, unit, smoke).

Acceptance
- Every completed task maps to at least one verification output.
- Regression rate remains below agreed threshold.

Rollback
- Freeze auto-execution and require human approval per task.

## Phase 4 - Reality loop hardening (Vera)

Objectives
- Make validation evidence-first and reproducible.

Deliverables
- Standardized evidence packaging.
- Consistent verdict schema and failure taxonomy.

Acceptance
- Every fail includes actionable reason + evidence link.
- Every pass includes proof artifacts.

Rollback
- Route uncertain cases to human review queue.

## Phase 5 - Gatekeeper promotion path

Objectives
- Promote only safe, validated changes.

Deliverables
- Gatekeeper decision artifact generated every run.
- Explicit pass/fail checks and reasons.

Acceptance
- No production promotion without `approved=true`.
- Full audit trail for all promoted runs.

Rollback
- Force all runs into non-promotable mode (`approved=false`).

## Phase 6 - Controlled self-improvement

Objectives
- Let system propose improvements without destabilizing core.

Deliverables
- Improvement inbox (`improvement_inbox/`).
- One-change-per-run policy enforcement.

Acceptance
- Improvement runs are reversible and measurable.
- Core contracts remain stable.

Rollback
- Disable self-improvement intake, continue normal delivery only.

## Metrics and observability

Track per week:

1. Dispatch success rate
2. Scrape completion rate
3. Gatekeeper approval rate
4. Regression incidents
5. Mean time to recover from failed run
6. Ratio of out-of-role violations

Minimum observability requirements:

- Every run has `run_trace.json`.
- Every fail has machine-readable reason.
- Every promotion has gatekeeper rationale.

## Operating cadence

Per run:

1. Generate artifacts stage-by-stage.
2. Validate contracts after each stage.
3. Execute tasks.
4. Validate in Vera.
5. Record gatekeeper decision.
6. Feed outcome to Auralis for next cycle.

Per sprint:

1. Review metrics trend.
2. Select one improvement target.
3. Run one controlled improvement cycle.
4. Promote only on full pass.

## Risks and mitigations

Risk: stage drift (reinterpretation)
- Mitigation: strict schema + role checks + fail closed.

Risk: unstable self-modification
- Mitigation: sandbox mirror + one-change policy + gatekeeper.

Risk: false pass from weak validation
- Mitigation: evidence requirements and reproducibility checks.

Risk: operational noise from stale runs/processes
- Mitigation: explicit run ownership, lock expiry, and failure artifacts.

## Immediate next actions

1. Implement artifact validators wired into run lifecycle.
2. Add a gatekeeper writer that emits `gatekeeper_decision.json` every run.
3. Add run trace writer in each stage handoff.
4. Pilot one full run with this plan and review deltas.

This plan defines the path from abstract intent to concrete tested outcomes while preserving role isolation and measurable reality feedback.
