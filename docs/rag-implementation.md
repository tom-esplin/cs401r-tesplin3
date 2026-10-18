# NorthStar offer generation: implementation and operation

The Track B pipeline reads policy documents, retrieves relevant policy excerpts
from a persistent local FAISS index, and generates a 2–3 sentence retention offer
with Bedrock. No Terraform apply, Studio domain, Glue job, or NAT Gateway is
required. The existing online Feature Store supplies live customer features.

## Benefit selection before generation

`rag/benefits.py` now selects one incentive before the model writes copy. It
reads tier values from the indexed loyalty-policy table, checks that the relevant
supporting sections exist, and records conditions, exclusions, citations, and
source chunk IDs. Points require the documented base earn rate; an unknown or
changed definition cannot authorize an interpreted rate. Column names determine
tier lookup, so reordering the table does not change eligibility.

The initial selectable incentives are standard points earning, early sale
access, and gear repair. Platinum prioritizes early access; Gold customers with
Outdoor/Footwear interests prioritize gear repair; other profiles prioritize
points. These are selection preferences, not new benefits or promotions. Tier
eligibility remains conditional unless independently verified. Annual repair
entitlement is not represented as a verified unused repair balance.

Birthday rewards and annual credits are excluded without verified eligibility or
remaining balance. Shipping incentives await destination/subtotal/surcharge
checks, and return-window incentives await purchase-time tier and item checks.
The selector records why those benefits were excluded instead of letting the
model infer eligibility from missing facts.

Application code renders approved offer options from the selected benefit's
unchanged sentence and a small set of category invitations. Bedrock returns a
structured object choosing an option, and `rag/claims.py` validates it before
returning customer-facing text. If policy evidence supports no candidate, the
model is not called and the conservative no-benefit response is returned.

Semantic retrieval remains in place. If it omitted a selected benefit's cited
policy section, the pipeline adds the original indexed passage to the evidence.
Derived benefit plans are not added to judge contexts as self-supporting facts.
The actual source passages, customer facts, and request remain the judge evidence.

## Structured claim validation

The `structured-claims-v1` contract requires exactly four fields:

```json
{
  "benefit_id": "points",
  "category": "Home",
  "eligibility_condition": {
    "tier": "Silver",
    "status": "conditional-tier",
    "conditions": [
      "Current Silver membership under trailing 12-month spend policy",
      "Qualifying merchandise spend"
    ]
  },
  "offer_text": "If your current tier is Silver, you earn 1.25 points per $1 of qualifying merchandise spend. Come back to NorthStar to explore Home."
}
```

The per-customer contract and approved options are supplied with each request.
The request also uses Bedrock's native `outputConfig.textFormat` JSON-schema
mode with a stable transport schema. It constrains field shapes and supported
enums; the application separately enforces the selected benefit, exact customer
eligibility conditions, category/text pairing, and approved visible copy.
This follows the official
[Bedrock structured-output request format](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html).
The decoder schema stays the same across customers so its compiled grammar can
be reused. First-use compilation can add latency, and that time is included in
the measured pipeline duration. The configured generator must support native
Bedrock JSON-schema output; the default Haiku profile was exercised successfully.
The boto3 minimum is the tested 1.43.91 release, whose Converse request model
includes `outputConfig.textFormat`.

Prompt-only JSON output was tried first, but all four responses were fenced in
Markdown even after correction and therefore used fallback copy. That run is
retained as diagnostic evidence; native schema output addresses the transport
failure without relaxing the application checks or stripping wrappers.
The application rejects malformed/fenced JSON, duplicate fields, non-finite JSON constants,
unknown or missing fields, and wrong types without coercion or JSON repair.

Schema-valid output must also match the preselected benefit, exact tier/status
and eligibility conditions, and a known customer category. The visible copy must
equal an approved option for that same category. Valid metadata cannot hide an
extra promise in free prose, and changing category metadata alone cannot approve
copy written for another category. The model never grants or verifies eligibility.

Approved invitations are simple category calls to action, such as "Come back to
NorthStar to explore Home." This deliberately limits wording variation: the
previous free-form invitation checks allowed unsupported phrases such as
"discover what's new". Only the chosen offer text is shown to the customer;
internal metadata remains in the run trace.

Invalid output gets one correction attempt. If it still fails, the application
builds a fallback with the same selected claim and validates it through the same
contract. A truncated/refused generation cannot bypass that gate. The raw model
response, parsed object, errors for each attempt, response contract, final
structured offer, and contract version are saved in `cases.jsonl`; `run.json`
also identifies the validation contract version.

## Setup and commands

Run from the repository root with AWS credentials for the lab account:

```powershell
python -m venv --system-site-packages .venv-rag
.\.venv-rag\Scripts\python.exe -m pip install -r requirements-rag.txt
.\.venv-rag\Scripts\python.exe -m rag build-index
.\.venv-rag\Scripts\python.exe -m rag offer --customer-id CUST-10000317
.\.venv-rag\Scripts\python.exe -m rag evaluate
```

For an isolated installation, omit `--system-site-packages`. The setup used here
reuses existing lab packages but installs RAG-specific changes inside `.venv-rag`.
Bedrock requests are billed; building a matching index again makes no embedding
requests. Generation and judging use the configurable Haiku inference profile;
the judge is billed separately. Credentials remain in the normal AWS credential
chain and are never written to run records.

Compare retrieval strategies with:

```powershell
.\.venv-rag\Scripts\python.exe -m rag --strategy benefits evaluate
.\.venv-rag\Scripts\python.exe -m rag --strategy constraints evaluate
.\.venv-rag\Scripts\python.exe -m rag --strategy combined evaluate
```

Use `evaluate --skip-judge` for generation-only diagnostics. This produces no
RAGAS scores and is not a passing evaluation. The legacy entry point
`python evaluation/evaluation_harness.py --track B` delegates to the same runner;
its `--output-dir` determines the parent folder for run records.

`offer --profile path/to/profile.json` accepts an explicit profile with
`churn_probability`, `loyalty_tier`, and `top_categories`. Other supported fields
include lifetime value, category diversity, recency, average order value,
online/store ratio, country, and a boolean `tier_verified` (default false).
The four supplied evaluation profiles remain fixtures; their values must not
be overwritten with live customer values because the ground truths match the
fixtures, not the current online store.

## Customer data path

For `offer --customer-id ...`:

1. Read current feature values from `northstar-dev-customer-features` online store.
2. Load `model/model.json`, order inputs using `model/model_metadata.json`, apply
   training's missing-value sentinel `-1`, and compute the churn probability.
   Do not substitute the feature store's heuristic `churn_risk_score`.
3. Read the customer's saved transactions from
   `snapshots/lab2/processed/customers/`; rank categories by summed `order_value`
   and select the top three recognized categories.
4. Retrieve policy and generate the offer. Keep provenance and the churn model's
   hash in the case trace. Only allowlisted profile fields go to the model.

`--categories Outdoor Footwear` and `--churn-probability 0.8` provide explicit
overrides when independently sourced inputs are available. Overrides are marked
as caller-supplied in provenance; they are not represented as model results.

The saved history is a historical Lab 2 snapshot, not a live purchase feed. Its
manifest is `snapshots/lab2/manifest.json`. Feature Store data may be newer.
Feature-store tiers approximate policy eligibility because they use lifetime
value rather than trailing 12-month qualifying spend. Offers therefore state
tier-specific benefits conditionally unless a caller supplies a verified tier.
No current unused-credit balance is available, so no offer claims one.

## Index and retrieval

`artifacts/rag/indexes/<index-id>/` contains `index.faiss`, `chunks.jsonl`, and
`manifest.json`. The version ID incorporates document hashes, embedding model,
dimensions, tokenizer, chunk size, overlap, and format version. Loading verifies
file hashes, vector count, and dimensionality. Complete versions are published
atomically; changed inputs require `build-index` before generation.

Chunking follows Markdown sections, repeats the source document title and table column headers, and uses
400 `cl100k_base` tokens including the prefix, with up to 60 tokens of overlap
within each section. Small sections remain smaller. Keeping table structure
helps preserve the association between a tier and its benefits. This tokenizer
sets chunk boundaries; it is not a claim about Titan's billing tokenizer.
The first build produced 51 chunks from the four policy documents.

Titan Text Embeddings V2 produces 1,024-dimensional vectors. FAISS uses exact
inner-product search over L2-normalized vectors (cosine similarity). Local
FAISS avoids an always-on vector service for this small corpus. A second
reranking model is omitted initially because the corpus is small and every
additional inference adds latency and cost.

The benefit strategy retrieves tier entitlements; the constraint strategy
retrieves exclusions. Combined retrieval reserves half its eight-passage budget
for benefits filtered to loyalty/shipping documents, then fills remaining slots
with deduplicated constraints from the whole corpus. Within the two ranked lists,
section metadata prioritizes tier benefits, tier definitions, points/credit terms,
shipping thresholds, final-sale rules, return mailing fees, and retention terms.
This deterministic coverage adjustment addresses semantic search missing essential
policy sections; there is no additional neural reranking model. Recorded scores
are the original vector similarities, not scores from the metadata adjustment.
Actual queries, scores, and passages are recorded per case.

Returned contexts include the allowlisted customer profile as well as retrieved
policy passages: both are evidence actually supplied to generation. This lets
the faithfulness judge assess personalization against customer facts rather than
incorrectly treating category preferences as unsupported policy claims. Ground
truths and expected answers are never supplied to generation or retrieval.

The Bedrock request formats follow the official
[Titan embeddings documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html)
and [Converse API documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html).

## Run records and retention

Every invocation creates `evaluation_results/rag/<UTC-timestamp>_<unique-id>/`
(or the configured `--run-root`). These are local files, not automatically
uploaded to S3 or logged to MLflow.

| File | Contents |
|---|---|
| `run.json` | Status, timestamps, configuration, model IDs, index ID, prompt hash, source hashes, Git revision/dirty state, and any fatal error |
| `system_prompt.txt` | Exact system prompt used for generation |
| `cases.jsonl` | Append-only case IDs, customer IDs/profiles, provenance, questions, retrieval queries, passages/scores, benefit plan with selected/candidate/excluded incentives and citations, added evidence IDs, structured response contract, raw/parsed attempts and errors, final structured offer, returned answer, fallback, generation usage, and latency |
| `scores.csv` | Judged runs only: case/customer IDs, RAGAS inputs, and per-case scores |
| `judge_traces.json` | Completed judged runs: metric prompts and judge outputs, including reasoning for failures |
| `summary.json` | Available usage totals, case/fallback counts, latency samples, and metric means/threshold checks when judging completes |
| `run.log` | Start/completion and execution errors |

Index-build runs have no case rows. Unjudged or failed runs do not manufacture
scores. Completed cases survive a later judge failure; interrupted processes
can leave status `running`, which must not be interpreted as completed.
Missing/NaN metric values fail the corresponding aggregate check.
Summaries also report model response count, rejected response count, and the
number of cases accepted from the model under the structured contract. The
evaluation CLI prints case and fallback counts after completion.

Generation token totals and observed Titan embedding input tokens are recorded.
The existing RAGAS wrapper does not expose aggregate judge token usage here;
records do not claim complete billed cost. Per-case pipeline latency includes
retrieval, generation, and validation/retry, but excludes customer loading,
initial index loading, and judging. It is not end-to-end display latency.

Detailed local artifacts and `.venv-rag` are Git-ignored. They persist until
explicitly removed; there is no automatic retention cleanup. Run records can
contain customer data, so only reviewed evaluation summaries belong in Git.

## Policy fixes and failure handling

The original marketing guidelines contain three planted errors: Gold's upper
threshold is $4,999.99, Platinum begins at $5,000, and no tier receives free
expedited shipping. Generation uses `rag/prompts.py`, not that erroneous block.
The prompt also resolves the template's length conflict to 2–3 sentences.

Prompts require policy-backed incentives and known categories, conditional tier
eligibility, and no invented promotions, products, or balances. Delivery now uses
the structured claim contract described above rather than phrase matching alone.
Correct delivery still depends on the policy parser/selector and the correctness
of source policy and customer data; RAGAS and manual review remain necessary.
A fallback is not evidence of successful model generation.

Primary failure modes are retrieving restrictions without useful entitlements
(addressed by two retrieval passes), granting benefits based on an approximate
tier (conditional wording), and inventing unsupported promotions (prompt,
validation, retry, then fallback). The report must preserve observed failures
and measured scores, including metrics below target.

## Verification

```powershell
.\.venv-rag\Scripts\python.exe -m unittest discover -s tests -v
```

Tests cover persistence, integrity and changed-policy invalidation, table header
preservation/token limits, filtered/deduplicated retrieval, feature input checks,
and rejected generation with retained failed-run records. Additional selection
tests cover every tier, unverified tier conditions, lifetime-spend independence,
missing/changed policy evidence, reordered columns, and invitations that attempt
to introduce a second incentive. Structured-output tests additionally cover forged
tier/verification/conditions, altered amounts, category/copy mismatches, added
promises, malformed/duplicate JSON, strict types, correction, and validated fallback.

Verified package versions for the initial build: Python 3.13, boto3 1.43.91,
FAISS 1.15.1, NumPy 2.2.2, pandas 2.3.3, tiktoken 0.11.0, RAGAS 0.4.3,
datasets 4.8.2, langchain 0.3.30, langchain-core 0.3.86,
langchain-community 0.3.31, and langchain-aws 0.2.35.
