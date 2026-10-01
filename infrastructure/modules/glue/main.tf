# ── modules/glue ─────────────────────────────────────────────────────────────
# Task 2: catalog database, raw-data crawler, and the transform ETL job.
# Task 3 adds a second job (feature-engineer) to this same module.
#
# Only the ETL job gets VPC networking, not the crawler: the Architecture
# Reference puts "Glue job workers" (not crawler workers) in the private
# subnet, and an S3-only crawler talks to S3/Glue over the public API, not
# through the VPC. The NETWORK connection below is what exercises the three
# VPC failure modes modules/iam and modules/vpc already provisioned for in
# Task 1 (glue:GetConnection, the self-referencing SG, ENI tagging).

resource "aws_glue_catalog_database" "this" {
  name = "${var.project}_${var.environment}"
}

resource "aws_s3_object" "transform_script" {
  bucket = var.bucket_name
  key    = "artifacts/glue/transform.py"
  source = "${path.module}/../../../glue-scripts/transform.py"
  etag   = filemd5("${path.module}/../../../glue-scripts/transform.py")
}

resource "aws_glue_connection" "network" {
  name            = "${var.project}-${var.environment}-glue-network"
  connection_type = "NETWORK"

  physical_connection_requirements {
    subnet_id              = var.private_subnet_id
    security_group_id_list = [var.glue_sg_id]
    availability_zone      = var.availability_zone
  }
}

resource "aws_glue_crawler" "raw" {
  name          = "${var.project}-${var.environment}-raw-crawler"
  role          = var.data_engineer_role_arn
  database_name = aws_glue_catalog_database.this.name

  s3_target {
    path = "s3://${var.bucket_name}/${var.raw_prefix}"
  }
}

resource "aws_glue_job" "transform" {
  name              = "${var.project}-${var.environment}-transform"
  role_arn          = var.data_engineer_role_arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  connections       = [aws_glue_connection.network.name]

  command {
    name            = "glueetl"
    script_location = "s3://${var.bucket_name}/artifacts/glue/transform.py"
    python_version  = "3"
  }

  default_arguments = {
    "--database_name" = aws_glue_catalog_database.this.name
    "--table_name"    = var.catalog_table_name
    "--output_path"   = "s3://${var.bucket_name}/${var.processed_prefix}"
  }

  depends_on = [aws_s3_object.transform_script]
}

resource "aws_s3_object" "feature_engineer_script" {
  bucket = var.bucket_name
  key    = "artifacts/glue/feature_engineer.py"
  source = "${path.module}/../../../glue-scripts/feature_engineer.py"
  etag   = filemd5("${path.module}/../../../glue-scripts/feature_engineer.py")
}

resource "aws_glue_job" "feature_engineer" {
  name              = "${var.project}-${var.environment}-feature-engineer"
  role_arn          = var.data_engineer_role_arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  connections       = [aws_glue_connection.network.name]

  command {
    name            = "glueetl"
    script_location = "s3://${var.bucket_name}/artifacts/glue/feature_engineer.py"
    python_version  = "3"
  }

  default_arguments = {
    "--input_path"         = "s3://${var.bucket_name}/${var.processed_prefix}"
    "--output_path"        = "s3://${var.bucket_name}/${var.features_prefix}"
    "--feature_group_name" = var.feature_group_name
    "--region"             = var.aws_region
  }

  depends_on = [aws_s3_object.feature_engineer_script]
}
