# Sprint A/B/C Task Index (Daily Ops)

Use this as the operational board for day-to-day execution.

Status values:
- `not-started`
- `in-progress`
- `blocked`
- `done`

## Current snapshot

| Sprint | Item | Owner | Status | Priority | Blocker | Artifact target |
| --- | --- | --- | --- | --- | --- | --- |
| A | A-1 Contract validator wiring | Krax | done | P0 | - | `runs/<job_id>/gatekeeper_decision.json` |
| A | A-2 Run trace writer at handoffs | Flash | done | P0 | - | `runs/<job_id>/run_trace.json` |
| A | A-3 Stage role violation fail-closed policy | Gatekeeper | done | P0 | - | `runs/<job_id>/gatekeeper_decision.json` |
| A | A-4 Gatekeeper contract baseline checks | Gatekeeper | done | P0 | - | `runs/<job_id>/gatekeeper_decision.json` |
| B | B-1 Mason decomposition quality checks | Mason | done | P1 | Sprint A complete | `runs/<job_id>/tasks.json` |
| B | B-2 Sprint slicer output format | Mason | done | P1 | Sprint A complete | `runs/<job_id>/tasks.json` |
| B | B-3 Flash execution manifest | Flash | done | P1 | Sprint A complete | `runs/<job_id>/execution_manifest.json` |
| B | B-4 Regression smoke suite integration | Vera | done | P1 | Sprint A complete | `runs/<job_id>/vera.json` |
| C | C-1 Vera evidence bundle standard | Vera | done | P2 | Sprint B complete | `runs/<job_id>/vera.json` |
| C | C-2 Gatekeeper promotion enforcement | Gatekeeper | done | P2 | Sprint B complete | `runs/<job_id>/gatekeeper_decision.json` |
| C | C-3 Feedback synthesis into revised `plan_v1` | Auralis | done | P2 | Sprint B complete | `runs/<job_id>/plan_v1_next.json` |
| C | C-4 One-change-per-run improvement pilot | Auralis | done | P2 | Sprint C prerequisites | `runs/<job_id>/feedback_summary.json` |

## Checklist by sprint

## Sprint A

- [x] A-1 Implement artifact validator wiring into run lifecycle
- [x] A-2 Write run trace events at each stage handoff
- [x] A-3 Enforce fail-closed behavior on stage-role violations
- [x] A-4 Emit gatekeeper baseline contract checks each run

Sprint A done criteria:
- [ ] Two consecutive runs contain all required artifacts
- [ ] Contract checks are machine-readable and pass/fail explicit
- [ ] Stage-role violations are blocked and logged

## Sprint B

- [x] B-1 Add Mason task quality checks (owner, done criteria, dependency order)
- [x] B-2 Add sprint slicer output constraints
- [x] B-3 Emit Flash execution manifest per run
- [x] B-4 Integrate regression smoke suite and capture results

Sprint B done criteria:
- [ ] Task completion without reinterpretation >= 90%
- [ ] Every completed task maps to at least one verification output
- [ ] Regression smoke remains green on two consecutive runs

## Sprint C

- [x] C-1 Standardize Vera evidence package and verdict schema
- [x] C-2 Enforce gatekeeper promotion policy (`approved=true` required)
- [x] C-3 Feed Vera findings into Auralis and produce revised `plan_v1`
- [x] C-4 Run one controlled one-change-per-run improvement pilot

Sprint C done criteria:
- [ ] No promotion occurs without complete gate check pass set
- [ ] Every fail has machine-readable reason and evidence link
- [ ] One full feedback loop reruns with revised plan artifact

## Daily update template

Use this section at the end of each day:

- Date:
- Active sprint:
- Completed items:
- Newly blocked items:
- Evidence links:
- Next item:

## Dependencies

- Sprint A must complete before Sprint B starts.
- Sprint B must complete before Sprint C starts.
- Sprint C promotion requires Gatekeeper checks passing.

## References

- `docs/sprint_board_abc.md`
- `docs/abstract_to_concrete_execution_plan.md`
- `docs/minimal_pipeline_spec.md`
- `contracts/runtime_artifacts/*.schema.json`
