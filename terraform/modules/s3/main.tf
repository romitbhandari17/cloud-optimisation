## Assessment reports bucket
#
# Deployed once in CLOUDINEER's own AWS account. Stores generated Assessment
# Dashboard JSON reports (docs/context.txt §8 "Reports: S3, QuickSight or web
# dashboard"), written by the dashboard Lambda in modules/agents.

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "reports" {
  bucket = "${var.project_name}-assessment-reports-${data.aws_caller_identity.current.account_id}"
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket                  = aws_s3_bucket.reports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "reports" {
  bucket = aws_s3_bucket.reports.id
  versioning_configuration {
    status = "Enabled"
  }
}
