# Evaluation and hidden-scenario review

The production package never imports these generators or their reference answers.
Tests use the standard-library `unittest` runner and assert financial values,
exclusion decisions, output coverage, entity relationships, failure policies and
complete CLI execution. They include an independent check that incorrect
exclusions cannot improve spend-weighted classification scores.

```bash
PYTHONPATH=src:. python3 -m unittest discover -s tests -v
PYTHONPATH=src:. python3 -m evaluation.adversarial --output private/adversarial_review
PYTHONPATH=src:. python3 -m evaluation.hidden --output private/hidden_review --seeds 61027 80413 91909
PYTHONPATH=src:. python3 -m evaluation.frozen --output private/schema_replay
PYTHONPATH=src:. python3 -m evaluation.benchmark --mode lexical --output private/scale_lexical
```

The generic hidden suite draws a latent event ledger before rendering records.
It covers two-source overlap/re-exports and VAT, multi-source currencies and
invoice-month fallback, and a new hospitality taxonomy with 24 variable-depth
leaves. It includes paraphrases, Spanish descriptions, ambiguous blank text,
negative credits and unapproved/cancelled/non-procurement records. The frozen
schema replay separately renders fresh synthetic records into the exact A/B
column layouts and uses byte-identical company configs. The failure-policy
matrix checks malformed data, invalid configuration and false duplicate removal.

For the optional local semantic model, use the documented semantic environment
and add `--classifier-mode semantic --python /absolute/path/to/python` to the
hidden command. The scale runner accepts `--mode semantic --python ...`.
It constructs 25,000 distinct evidence strings and eligible purchases, so repeated
text caches cannot make a small semantic workload appear to be a 25,000-query
benchmark. The timed subprocess includes model startup; model download and
installation are separate prerequisites.

All generated inputs, event ledgers, reference answers, predictions and detailed
reports remain in the ignored `private/` directory. Each evaluation records code,
config and input hashes, then saves and hashes predictions before opening truth.
Truth is absent from the subprocess's input directory and is never passed as a
runtime argument. The process retains the user's filesystem permissions: this is
input separation, not an OS security sandbox. Verify the before/after snapshot
matches when reporting a frozen final run. An opened scenario becomes development
data; use fresh seeds after a fix and retain earlier failures.

These are self-authored synthetic checks, not an independent external blind test.
They measure the declared fixture distribution and cannot establish performance
on the organisers' unknown industry or hidden labels. Distinguish generic-schema
results from the stricter unchanged-config replay. Missing evidence can legitimately
reduce matching recall; do not remove ambiguous purchases to improve totals.

Saved real-data zero-label predictions can be evaluated only after they exist:

```bash
PYTHONPATH=src:. python3 -m evaluation.real \
  --prediction private/labels_hidden/A_lexical.csv \
  --labels company_A/labels_A.csv \
  --raw company_A/erp_goods_receipts.csv \
  --output private/evaluation/A_labels_hidden.json
```

The example prediction must have been produced without an artifact, before labels are opened. Final artifact-assisted submission predictions are trained on supplied labels and are not a labels-hidden evaluation. No labels are supplied to production by this evaluation command. A's labels cover category
and supplier/item identity, rather than definitive cross-system transaction
relationships. B's seed labels are incomplete and imperfect. The evaluator reports
coverage explicitly and treats A's supplied net ERP amount as the reference weight.
Do not interpret B local-currency weights as USD-weighted accuracy. Grouped split
reservations are stored privately before fitting; a reservation alone is not a
trained-model evaluation result.
