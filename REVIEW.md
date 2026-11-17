# Implementation and hidden-scenario review

Measured locally on 17 November 2026. The implementation, configs, required documents and A/B exports are present. This review distinguishes observed correctness, development comparisons and remaining uncertainty; it is not a prediction of the organisers' score.

## Completed work

The eight tasks in [TASKS.md](TASKS.md) cover protection/contracts, ingestion/finance, entity/matching, classification, independent evaluation, integration/exports, hidden review/fixes and documentation. Three agents worked in parallel after the canonical/config contracts were agreed. The main process integrated and reviewed their work.

Implemented commands are `run`, `train`, `evaluate` and `validate`. JSON configs are dependency-free; YAML is optional. Classification supports both a local/no-key lexical route and a pinned offline semantic model. Supplied-label training is explicit and produces ignored private artifacts. New companies use data-only configs and runtime taxonomy files.

`.gitignore` was created before any repository work. Confidential company inputs, the brief, plan/instructions, private diagnostics, splits, caches and trained models are protected. Ignore tests check that required submission CSV names remain eligible. A built wheel was inspected: it contained only production/evaluation packages and package metadata, with no confidential inputs. No workspace Git repository, remote publication or form submission was performed.

## Whole-flow verification

**79 tests passed, zero skipped in the model-enabled environment.** The minimal standard-library environment also runs the suite, with five optional model-dependent tests skipped. Tests exercise actual CLI invocations and independent financial/event-ledger expectations. They cover tax, FX direction/fallback, signed credits, date ambiguity, statuses, count-once capacity, re-exports, specification conflicts, blank evidence, malformed inputs/trees/configs, train-before-vocabulary boundaries, artifact fallback, and output replay validation.

Final official-format outputs contain **65,549 A rows** and **41,028 B rows**, exactly matching input coverage. Both passed contract checks and financial/matching replay. Independent repeat runs produced identical CSV SHA-256 hashes for both files.

| Output | Rows | Included | Pipeline time, first final run |
| --- | ---: | ---: | ---: |
| `submission/Ayush_Kumar__A.csv` | 65,549 | 54,117 | 11.65 s |
| `submission/Ayush_Kumar__B.csv` | 41,028 | 38,987 | 88.42 s |

These runs include classification, optional artifact loading/inference and export. Full-data training is a separate setup step: A **44.51 s**, B **4.79 s**. A repeat under concurrent load took 14.45 s and B 130.57 s, without changing output bytes. General-purpose weights were already installed. Reference environment: Python 3.11.14, macOS 26.5.1, ARM64, CPU inference; exact ML dependency versions are in `requirements-ml.txt`. Hardware model/RAM could not be queried through the sandbox; peak memory was not measured.

## Loopholes found and fixed

The original independent adversarial audit passed **13/22** cases. After repairs, the same cases pass **22/22**. Two additional failures found in the expanded review were also fixed: the final expanded audit passes **24/24**. Separate entity/matching regressions preserve twelve assertions that failed before their corresponding fixes; these are not added to the independent audit count.

| Failure mechanism | Repair and evidence |
| --- | --- |
| Negative/NaN tolerance, out-of-range similarity, zero/fractional candidate limit, negative date window | Reject six invalid matching configurations before processing. |
| Distinct receipts, invoice lines or conflicting scoped supplier IDs could be removed | Explicit identity conflicts prevent matching. Each original two-row case now retains the independently expected 200 rather than 100 synthetic spend. |
| Relative tolerance could match large but distinct amounts | Default relative tolerance is zero; the adversarial case now retains expected 200,050 instead of 100,000. |
| Similar supplier names differing in meaningful words could match | Compare informative tokens conservatively while retaining OCR/reordering support. |
| Decimal PO line suffixes and reference prefixes were mishandled | Normalise integral decimal components and strip only genuine reference prefixes. |
| Excluded rows changed active aliases; reused IDs merged differing specifications | Build alias evidence only from eligible records and preserve conflicting ordered specifications. |
| Malformed taxonomy rows and duplicate headers could be accepted | Reject malformed schema/row widths while allowing explicit blank levels below shallow leaves. |
| A finite altered amount could pass structural validation | Replay financial, eligibility, grouping and matching decisions during validation. |
| Output could overwrite a source/config file | Protect input/config/diagnostic paths and use atomic export. |

Actual A heuristic cross-source links increased **8,703 → 10,625**, or **+1,922 / +22.08%** after all safeguards. Tool re-exports changed **318 → 304** because more precise line identity avoided some previous fingerprint collisions. These are measured decision counts, **not verified real duplicate accuracy**; the supplied kit has no complete duplicate gold standard. Intermediate results with more aggressive matching are superseded.

## Measured classification changes

| Evaluation and comparison | Before exact path | After exact path | Gain |
| --- | ---: | ---: | ---: |
| Synthetic C, same 1,500-row seed: lexical → semantic | 76.95% | 88.32% | +11.37 percentage points |
| A held-out item/description groups: lexical → supervised + lexical | 13.04% | 45.33% | +32.30 pp |
| A held-out suppliers: lexical → supervised + lexical | 12.45% | 21.20% | +8.75 pp |
| B held-out source systems: semantic → supervised + semantic | 57.52% | 60.34% | +2.82 pp |

The grouped comparisons are **development evaluations**, not freshly sealed real tests. Reservations preceded fitting; only development groups fit vocabulary/model parameters. Test support was 6,214 A item-group rows, 13,002 A supplier-group rows and 1,170 B category-labelled rows. The architecture and 0.55 threshold were fixed before those evaluations. Full-data baseline aggregates had already been inspected, so the reports do not claim untouched real test provenance.

The genuine labels-hidden A run remains weak: **12.10% exact path** with lexical retrieval versus **10.14%** with semantic retrieval; L1 lexical accuracy is **37.49%**. A's weighted exact lexical score is **19.99%** using absolute supplied ERP net spend. The semantic method was therefore not presented as a universal improvement. B's genuine no-label exact-path baseline improves **28.71% → 35.88%**, on 2,550 category-labelled seeds. B mixed local-currency weights are not reported as USD-weighted accuracy.

Final artifacts fit all authorised labels for submission. Scores on those same labels are in-sample and are deliberately excluded from generalisation claims. Confidence remains uncalibrated; reliability/Brier diagnostics are private. No temporal-fit evaluation was completed.

## Fresh frozen synthetic scenarios

The semantic model/config/code snapshot was fixed before generating seeds **80413, 91909 and 120117**. Nine A/B/C runs contained **8,314 rows**; all had zero output-contract errors, zero known-ledger financial error and inclusion macro-F1 of 100%. Generic A scenarios found all 697 known duplicates with no false removals. Their structured identity evidence is easier than the stricter schema replay below.

Across three C runs, each containing 1,500 rows and an unseen runtime tree with 24 variable-depth leaves:

- Exact-path accuracy: **88.01% mean**, range **87.15–88.53%**.
- L1 accuracy: **91.59% mean**.
- Absolute-reference-spend-weighted exact accuracy: **88.49% mean**.
- Informative-record exact accuracy: **90.70% mean**.

The production process received no labels/artifacts. Predictions were saved/hashed before scoring. Truth was outside its input directory, but the OS permissions were shared; this is not strong filesystem isolation. These are self-authored hospitality scenarios and do not establish performance on a genuinely independent industry.

A separate rehearsal rendered new synthetic rows into the actual A/B layouts and used their configs byte-for-byte. A's **674-row** replay had duplicate precision **100%**, recall **94.78% (236/249)**, and no legitimate removals. Thirteen true duplicates with blank descriptions and no item IDs remained unmatched, causing **+3.56% spend overcount**. B's **600-row** replay had zero financial/contract errors. The frozen A lexical method scored 56.10% on this deliberately different synthetic hospitality tree; this is separate from C's semantic result.

## Scale and rehearsal budget

The final cold subprocess processed **25,000 eligible rows with 25,000 distinct semantic evidence strings in 142.06 seconds (2.37 minutes)**, including model startup, with zero contract errors and zero ledger spend error. Model installation/download was excluded. An earlier run took 90.41 seconds; concurrent CPU load increased the final measured time, so 142.06 seconds is the reported final result.

The sum of the first final A and B pipeline durations and the 25,000-row C wall time is **242.13 seconds (4.04 minutes)** for **131,577 rows**. Adding both measured final training durations gives about **4.86 minutes**. This is a sum of observed component runs, not a timed organiser A2/B2/C job; incoming sizes, C configuration and publication time remain unknown.

Final numerical suites recorded an unchanged complete source/config/dependency/evaluator snapshot. Afterwards only the evaluator's provenance wording was corrected to avoid incorrectly calling arbitrary saved predictions “zero-label”; scoring, production and configs were unchanged. That correction is recorded privately.

## Remaining limits

- Three blank B amounts and five unavailable invoice-month FX rates use explicitly flagged estimates. The three unit-price medians happen to yield zero; their true invoice amounts remain unknown. These eight records are not verified financially correct. Default/new-company policies remain strict. See [DECISIONS.md](DECISIONS.md).
- Against all 3,000 supplied B inclusion labels, non-procurement precision is 100%, recall **80.89% (364/450)**; 86 supplied non-procurement labels remain included. Inclusion macro-F1 is **93.89%**. These labels are incomplete/noisy; no hidden-test claim follows.
- Entity grouping is conservative. The original labels-hidden A grouping diagnostic had supplier pairwise recall about 10% and item recall about 50%; learned category models do not repair that identity gap. Final specification safeguards can further split groups. No strong real grouping-quality claim is made.
- Split/partial invoices, transitive three-source matching and missing critical evidence remain unresolved conservatively. Candidate limits/ambiguity can retain duplicate spend.
- C confidence is transferred/uncalibrated, zero-label A quality is weak, and synthetic success does not guarantee unseen-company quality.

[Machine-readable aggregate results](evaluation_results.json) accompany this report. Detailed raw traces, source hashes, splits, predictions, failure logs and trained artifacts remain under ignored `private/`.
