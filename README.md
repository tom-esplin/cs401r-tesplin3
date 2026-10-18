# cs401r-lab1-template
CS 401R Lab 1: Platform Foundation — starter template (do not fork directly)

## Lab 3: Offer generation (RAG)

The Track B implementation uses Bedrock, a persistent local FAISS policy index,
and the existing customer Feature Store. See
[`docs/rag-implementation.md`](docs/rag-implementation.md) for setup, commands,
architecture, and the exact location and contents of run records.

## Lab 3: Churn training and submission checks

Run commands from the repository root. Create a Python 3.13 environment with
the SageMaker 2.x SDK required by the Feature Store loader:

```powershell
py -3.13 -m venv .venv-churn
.\.venv-churn\Scripts\python.exe -m pip install -r requirements-churn.txt
```

Train locally against the existing Lab 2 Feature Store offline data. The wrapper
reads `s3_bucket_name`, `feature_group_name`, and `ml_engineer_role_arn` from
`terraform -chdir=infrastructure/environments/dev output -json`. It creates no
bucket, role, endpoint, or training job, and never runs Terraform apply.

```powershell
.\.venv-churn\Scripts\python.exe scripts/train_lab3.py --dry-run
.\.venv-churn\Scripts\python.exe scripts/train_lab3.py -- `
  --max-depth 3 --eta 0.1 --num-round 200 --seed 42 --test-size 0.30 `
  --mlflow-arn $env:MLFLOW_APP_ARN --run-name xgb-depth3-weighted
```

Set `MLFLOW_APP_ARN` to the existing serverless MLflow App ARN before this
tracked run. Omit the `--mlflow-arn` pair for an untracked development run.
Local runs use the AWS credential chain; `--execution-role-arn` records the
existing SageMaker role as provenance and does not assume it. A SageMaker
training job, if used, must pass the Terraform `ml_engineer_role_arn` output
as its execution role. That role trusts SageMaker, not a local caller.

Training also evaluates the model: AUC, precision/recall at the global top-10%
cutoff, paired-bootstrap lift over the trained recency-only baseline, and
loyalty-tier slices. Defaults preserve the submitted split and training settings.
`--help` lists all tuning arguments, including early stopping, ordered evaluation
metrics, and baseline hyperparameters. Changing split or tuning settings requires
a fresh evaluation; existing reported metrics describe the saved model only.

| Artifact | Default location |
|---|---|
| Saved model and complete resolved training configuration | `model/model.json`, `model/model_metadata.json` |
| Aggregate and slice evaluation | `output/evaluation_metrics.json`, `output/slice_metrics.json` |
| Tracked runs | Existing MLflow App, experiment `northstar-churn` |
| Final registered model (`--register` only) | Existing bucket: `artifacts/models/churn/<timestamp>/model.tar.gz`; Model Registry group `northstar-churn-models`, PendingManualApproval |
| Athena query results | Existing bucket: `artifacts/athena-results/` |
| RAG index and evaluation traces | `artifacts/rag/indexes/`, `evaluation_results/rag/<run-id>/` |

Use `--model-dir` and `--output-data-dir` to isolate experiments from the saved
submission artifacts. `--local-data-path path/to/features.csv` bypasses Athena
for development; rubric evidence should retain the Feature Store provenance.
Register only the selected final run by adding `--register` to its arguments.
RAG generation/evaluation commands and dependencies are in
[`docs/rag-implementation.md`](docs/rag-implementation.md).

Before submission, run the cleanup script using Bash (Git Bash on Windows):

```bash
bash scripts/teardown-lab3.sh
# Later, refresh the evidence without changing resources:
bash scripts/teardown-lab3.sh --verify-only
```

The script writes `docs/lab3-teardown-output.txt` with account, region, timestamp,
and checks for endpoints/configs, active or stopping training/processing/transform
jobs, and MLflow Tracking Servers. Wait for stopping jobs to finish and rerun
until all checks pass. Keep the serverless MLflow App. The teardown script
reports any MLflow Tracking Server for manual deletion; it does not delete it.
Submit `docs/bedrock-access-verification.txt` with the two Pre-Lab 3 access checks,
and the completed `docs/lab3-model-design.md` alongside the evaluation evidence.
The repository supplies a repeatable check of the two runtime capabilities used
by Track B (Claude generation and Titan embeddings):

```powershell
.\.venv-rag\Scripts\python.exe scripts/verify-bedrock-access.py --region us-east-1
```

This makes two small billed requests and writes the verification file above.
Its check definitions are explicit; compare them with the Pre-Lab handout if
the course prescribes different checks.

## Lab 2 Additions

Lab 2 hardens the Lab 1 platform and adds the data pipeline on top of it. See
[`infrastructure/README.md`](infrastructure/README.md) for the full Terraform
module layout — summary of what's new:

- **Private subnet + NAT Gateway** (`modules/vpc`) — the SageMaker Domain and
  Glue job workers now run in a private subnet with no direct inbound route;
  outbound internet access goes through the NAT Gateway.
- **`DataEngineer` and `ModelMonitor` IAM roles** (`modules/iam`) — least-privilege
  roles for the Glue pipeline and for (future) model monitoring, alongside the
  existing `MLEngineer` role.
- **S3 lifecycle rules** (`modules/storage`) — expiration/version-cleanup rules
  on `raw/`, `processed/`, `features/`, and `datacapture/`.
- **The ingestion + feature pipeline** (`modules/glue`, `modules/feature_store`) —
  a Glue crawler discovers the raw CSV schema, two Glue ETL jobs
  (`glue-scripts/transform.py`, `glue-scripts/feature_engineer.py`) clean the
  data and compute churn features, and a SageMaker Feature Group makes the
  features available online and offline.

### Running the data pipeline end-to-end

Once `terraform apply` has created the stack in `infrastructure/environments/dev`:

```bash
ACCT=$(aws sts get-caller-identity --query Account --output text)
BUCKET=northstar-dev-data-${ACCT}

# 1. Land raw data
aws s3 cp northstar-raw-sample.csv s3://${BUCKET}/raw/customers/northstar-raw-sample.csv

# 2. Discover its schema
aws glue start-crawler --name northstar-dev-raw-crawler

# 3. Clean + dedupe it into processed/customers/ (Parquet)
aws glue start-job-run --job-name northstar-dev-transform

# 4. Compute churn features into features/customers/ + the Feature Group
aws glue start-job-run --job-name northstar-dev-feature-engineer

# 5. Check everything against the rubric's own assertions
bash scripts/verify-lab2.sh
```

Each step depends on the previous one finishing (`aws glue get-crawler`/
`get-job-run` to poll status) — see the Lab 2 doc's Task 2/3 sections for the
exact wait/verify commands.

### Tearing down

The NAT Gateway bills whether or not it's used, and several resources (Glue
ENIs, the SageMaker Studio EFS filesystem, the Feature Store's auto-created
Glue database, SageMaker lineage contexts) are created outside Terraform's
state and survive a plain `terraform destroy`. Use `scripts/teardown-lab2.sh`
instead — it removes all of that in the right order and verifies nothing
billable remains.
