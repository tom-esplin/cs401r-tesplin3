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

For what Lab 2 added on top of this (the Glue/Feature Store pipeline) and how
to run it end-to-end, see the [top-level README](../README.md).
