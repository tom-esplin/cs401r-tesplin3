# ── modules/storage ──────────────────────────────────────────────────────────
# Required resources (Task B1). Only these belong in this module:
#
#   aws_s3_bucket
#   aws_s3_bucket_public_access_block
#   aws_s3_bucket_versioning
#   aws_s3_bucket_server_side_encryption_configuration
#   aws_s3_object  x4                 the raw/ processed/ features/ artifacts/ prefixes
#
# ONE bucket with four prefixes, not four buckets. Later labs derive the name
# as ${project}-${environment}-data-${account_id}, so keep that shape.
#
# The four aws_s3_object resources create the prefixes. S3 has no real
# directories; an empty object with a trailing slash is how a prefix is made
# to exist before anything is written to it.

# TODO: implement the resources above.
resource "aws_s3_bucket" "this" {
  bucket = "${var.project}-${var.environment}-data-${var.account_id}"

  tags = {
    Name = "${var.project}-${var.environment}-data-${var.account_id}"
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # SSE-S3
    }
  }
}

resource "aws_s3_object" "prefix" {
  for_each = toset(var.prefixes)

  bucket  = aws_s3_bucket.this.id
  key     = each.value # e.g. "raw/"
  content = ""
}
