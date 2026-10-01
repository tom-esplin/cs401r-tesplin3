# Terraform Module Template — Lab 1 Part B

Skeleton for Task B1. **It is empty on purpose**: every file declares its
variables and outputs, and `main.tf` lists the resources you owe, but no
resources are written for you.

Verify it starts clean before you add anything:

```bash
cd environments/dev
terraform init
terraform fmt -check -recursive ../..   # no output = pass
terraform validate                      # exits 0
```

Both must still pass when you submit — that is 5 of the 15 points in B1.

## Layout

```
modules/vpc/        aws_vpc, aws_subnet (public + private), aws_internet_gateway,
                    aws_nat_gateway + aws_eip, aws_route_table x2, aws_route_table_association x2,
                    aws_security_group (sagemaker), aws_security_group (glue, self-referencing)
modules/storage/    aws_s3_bucket + public_access_block, versioning,
                    server_side_encryption_configuration, aws_s3_object x4 (prefixes),
                    aws_s3_bucket_lifecycle_configuration
modules/iam/        aws_iam_role/policy/attachment x3 (MLEngineer, DataEngineer, ModelMonitor)
modules/sagemaker/  aws_sagemaker_domain, aws_sagemaker_user_profile
modules/glue/       aws_glue_catalog_database, aws_glue_connection (NETWORK),
                    aws_glue_crawler, aws_glue_job x2 (transform, feature-engineer),
                    aws_s3_object x2 (uploads the two glue-scripts/*.py files)
modules/feature_store/  aws_sagemaker_feature_group (16 feature_definition blocks)
```

Each module contains **only** its designated resources — that is graded.

## The rule that catches people

**No hardcoded names.** The rubric runs:

```bash
grep -rn '"northstar-dev"' infrastructure/modules/
```

and expects nothing. Build names from `var.project` and `var.environment`
(`"${var.project}-${var.environment}-data"`), and give every variable a
`description` — that is also graded.

## Lab 2 Additions

Lab 2 hardens the Lab 1 platform and adds the data pipeline on top of it:

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

Once `terraform apply` has created the stack in `environments/dev`:

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
