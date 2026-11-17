# Decisions and assumptions

No organiser questions were asked. These policies resolve ambiguity explicitly and remain configuration-driven.

## Input and output identity

Every raw purchase row is retained, including exclusions. Source ID prefixes are configured. Required IDs must be nonempty and unique across the run. Source namespaces are stable across directory changes; a vendor/material number in a different source system does not by itself establish identity. CSV decoding is UTF-8 with optional BOM. Malformed field counts and duplicate headers fail.

The output uses exactly the specified eleven columns. Excluded rows have zero spend, blank categories, confidence zero and one allowed reason. Reason precedence is `CANCELLED > NOT_APPROVED > NON_PROCUREMENT > DUPLICATE`. Unknown financial inputs do not create an invented exclusion code. Output writes cannot overwrite raw input, taxonomy, FX or config files. Successful exports are atomic; a failed run leaves any older output unchanged, so always check its exit code and current run hashes.

## Financial semantics

A goods-receipt values are already net ZAR, including rows whose document currency differs. The document-currency field is not mapped as the amount currency. A tool values are gross. VAT fractions, numeric percentages and `%` strings are accepted; blank VAT uses the explicitly configured 15%. Valid zero VAT is preserved. Bare numeric VAT at or below one is a fraction; use a `%` suffix to disambiguate one percent.

Number parsing has explicit decimal/thousands separators and validates grouping. Credits retain their sign. Parenthesised negatives work; a second sign inside parentheses fails. Each included reporting amount is rounded half-up to cents after tax and conversion. Matching compares these reporting amounts with a small absolute tolerance; relative tolerance defaults to zero to protect large distinct purchases.

B line rates and monthly rates are units per USD, so amounts are divided. USD needs no rate. Missing, malformed or nonpositive line rates fall back to the invoice-month rate, never the posting month. Missing/invalid dates are flagged; they do not automatically reject procurement. A non-USD record without a usable date still works if it has a valid line rate. Duplicate identical monthly FX entries are allowed; conflicting or nonpositive table entries fail.

**Explicit B estimation exceptions:** three supplied records have blank amounts. No exact value can be recovered from their own fields. B enables the median net USD unit price from at least two eligible peers sharing the same source-scoped material, multiplied by the record's quantity. Those estimates are flagged with support and peer ranges; the supplied peers yield zero estimates, which are estimates rather than evidence of known zero invoices. Five other records lack both a line rate and a rate for their old invoice month. B enables the closest supplied currency/month rate within 24 months (ties favour the earlier month), with the chosen month/gap flagged. These eight records remain a known uncertainty in total spend. The default for both problems is an error; unseen C's template keeps strict policies. No claim of one-cent correctness applies to these unknown values.

## Eligibility

A ERP is a completed goods-receipt ledger with no invoice approval field. Its missing-status policy explicitly accepts these receipt records. A tool explicitly accepts only approved/paid status; cancelled rows and other statuses receive the corresponding reason.

B is supplied as a posted accounts-payable invoice ledger without an approval/status field. The documented assumption accepts missing status at this source, rather than rejecting the entire ledger or inventing meanings for opaque document-code prefixes. This cannot verify every invoice's actual approval state.

Non-procurement decisions use explicit structured account semantics or narrowly anchored transaction phrases. The B config treats intercompany account descriptions as internal transfers. Opaque supplier/document/account numbers alone are not assigned business meanings. Broad substring matching on words such as “tax” or “finance” is avoided so legitimate professional services remain eligible. Supplied B seed exclusion labels are noisy; remaining disagreement is reported, not treated as verified hidden truth.

## Entity and purchase identity

Supplier IDs are authoritative within their configured namespace. Unambiguous exact normalised names can anchor ID-less variants; legal endings and typography are normalised. Similar names alone do not merge distinct ID-backed suppliers. Shared source-local numbers do not merge across systems. Excluded records cannot change valid-record alias evidence.

Items use scoped material IDs, with numeric specification safeguards where the same ID visibly describes conflicting specifications. Informative descriptions may anchor ID-less rows; generic/blank text gets a separate unresolved key. Dimensions and ordered numbers are preserved. This favours precision and can split real equivalent items; real grouping recall is limited and disclosed.

Purchase identity is separate from supplier/item identity. Re-export detection is opt-in per source and requires a composite invoice/item/quantity/value/date/reference fingerprint. An invoice number alone never suffices. Confirmed cross-source matches prefer configured source priority, compare tax-normalised values and quantity, and require supplier/item evidence. Explicit receipt, invoice-line, scoped supplier-ID and technical-specification conflicts prevent removal. Candidate blocks are bounded; ambiguous ties and oversized blocks stay included and are diagnosed. Cancelled or other excluded records consume no match capacity.

The matcher supports conservative one-to-one reconciliation. Partial/split invoices, uncertain missing-reference matches and transitive matches across three sources are retained rather than guessed. The input does not supply complete duplicate truth; increased A link counts are heuristic coverage, not verified recall.

## Classification and evaluation

The runtime tree defines exact valid leaf paths, including variable depth and repeated leaf names. Production contains no company/category conditionals, labelled exemplars or category-specific synonym tables. Input instructions remain plain text data. C runs without labels, supplied-label artifacts or inherited taxonomy caches.

The no-label routes are lexical retrieval and the pinned general-purpose LaBSE encoder. The optional model uses word/character TF-IDF plus logistic regression on explicitly permitted labels. IDs, row position, supplier names and keys are not predictive features. Vocabulary fitting occurs only after partition filtering. A fixed probability threshold of 0.55 permits supervised replacement; unseen/OOV classes retain taxonomy retrieval. Confidence is uncalibrated and must not be interpreted as a guaranteed probability, especially for C.

Item/description groups, supplier groups and entire B sources were reserved before fitting. Baseline saved predictions were scored before optional supervised training. Because full-data baseline aggregates were already opened, subsequent grouped comparisons are development evaluations, not fresh sealed tests. Full-data final artifacts are used for submission only; no training-set accuracy is presented as generalisation. No architecture/threshold tuning followed those grouped scores.

Self-authored final scenarios use new seeds after the implementation snapshot. Truth stays outside the inference input directory, predictions are saved/hashed before scoring, and runtime code does not import the generator. This is logical/process separation under the same user's filesystem permissions, not OS-enforced isolation; an attempted nested OS sandbox was unavailable. Synthetic results cannot establish performance on the organisers' industry or real duplicate truth.

All purchase text and learned artifacts stay local. Development used AI coding assistance, ordinary Python tooling, a general-purpose local sentence encoder and a local supervised model. No external LLM/API received task rows; paid API cost is zero. Confidential derived diagnostics and models remain ignored. Public docs contain aggregate results only.
