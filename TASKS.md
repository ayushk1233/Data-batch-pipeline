# Implementation tasks

The original plan remains the design reference. Implementation was authorised on 17 November 2026. All eight implementation tasks are complete with measured evidence in REVIEW.md and evaluation_results.json; remaining quality limits and unachieved acceptance targets are explicitly reported there.

| Task | Dependency | Owner | Evidence required |
| --- | --- | --- | --- |
| 1. Protect confidential inputs and define contracts | None | Main | Ignore checks, strict config and output validation |
| 2. Ingest, normalise tax/FX, apply eligibility, export | 1 | Main | Financial unit tests and complete A/B runs |
| 3. Resolve suppliers/items and count purchases once | Canonical record contract from 1; parallel with 2 | Matching agent | Known-truth duplicate and false-removal tests |
| 4. Runtime taxonomy and labels-free classification | Canonical record contract from 1; parallel with 2/3 | Classification agent | Lexical/semantic comparison, valid variable-depth paths |
| 5. Independent flow tests and hidden event-ledger harness | Config contract from 1; parallel with 2/3/4 | Evaluation agent | Baseline, frozen hashes, fresh seeds, scale rehearsal |
| 6. Integrate CLI, configs and real outputs | 2/3/4 | Main | One-command run, exact coverage, deterministic rerun |
| 7. Review hidden failures and repair loopholes | 5/6 | Main with agents | Before/after numbers; newly sealed final scenarios |
| 8. Document evidence, limits and blind-test runbook | 6/7 | Main | README, APPROACH, DECISIONS, aggregate review |

No publication, organiser messages, Git initialisation, or submission-form action is included in this development request. No tests may substitute placeholder assertions for behaviour checks. Real duplicate accuracy is unknown without reviewed duplicate truth; synthetic accuracy must be labelled as synthetic.

## Completion evidence

T1: ignore/protection tests and strict contracts. T2-T4: complete configurable pipeline and optional local model training. T5/T7: 79 passing tests, 24/24 adversarial checks, nine fresh synthetic runs plus stricter unchanged-config replay and a 25,000-unique-input benchmark. T6: exact A/B row coverage, replay validation and identical repeat CSV hashes. T8: README, one-page APPROACH, DECISIONS, REVIEW and machine-readable aggregates. Completion does not mean every quality target was achieved: weak A zero-label accuracy, conservative grouping/matching, B estimates and missing temporal/memory measurements remain documented limits.
