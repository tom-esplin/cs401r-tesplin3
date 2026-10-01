# cs401r-lab1-template
CS 401R Lab 1: Platform Foundation — starter template (do not fork directly)

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
