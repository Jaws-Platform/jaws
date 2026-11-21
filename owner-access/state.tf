# This stack's own state bucket, in the management account beside the
# organization and Identity Center it manages.
#
# The state stays out of the production account's shared bucket on purpose:
# this is the break-glass stack that grants access to every account, so fixing
# that access must not depend on access to another account. The bucket was
# created by hand before the first `terraform init` that uses it (a backend
# cannot create its own bucket) and is adopted here by the imports below.
#
# Its policy only requires TLS. The account holds nothing but the organization,
# Identity Center and billing data, and its only principals are the owner's
# admin role and root, so there is no CI role to fence off, and no role ARN is
# pinned that a recreated permission set could lock out.

locals {
  state_bucket_name = "jaws-owner-access-state-${local.account_id}"
}

import {
  to = aws_s3_bucket.state
  id = local.state_bucket_name
}

import {
  to = aws_s3_bucket_versioning.state
  id = local.state_bucket_name
}

import {
  to = aws_s3_bucket_server_side_encryption_configuration.state
  id = local.state_bucket_name
}

import {
  to = aws_s3_bucket_public_access_block.state
  id = local.state_bucket_name
}

import {
  to = aws_s3_bucket_ownership_controls.state
  id = local.state_bucket_name
}

import {
  to = aws_s3_bucket_policy.state
  id = local.state_bucket_name
}

resource "aws_s3_bucket" "state" {
  bucket = local.state_bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

# Every prior state stays recoverable.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

data "aws_iam_policy_document" "state" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.state.json

  depends_on = [aws_s3_bucket_public_access_block.state]
}
