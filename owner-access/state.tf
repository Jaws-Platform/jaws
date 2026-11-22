# This stack's own state bucket, in the management account beside the
# organization and Identity Center it manages.
#
# The state stays out of the production account's shared bucket on purpose:
# this is the break-glass stack that grants access to every account, so fixing
# that access must not depend on access to another account. The bucket was
# created by hand before the first `terraform init` that uses it (a backend
# cannot create its own bucket) and is adopted here by the imports below.
#
# Its policy requires TLS and denies every principal except the owner's
# Identity Center admin role and root: this state names every account the
# owner can reach, and no one else, not even another admin in this account,
# needs it. No CI role applies this stack, so none is listed. Like the shared
# bucket's policy (foundation/state.tf), every statement is a deny: it bounds
# what IAM allows and grants nothing.
#
# The admin role is matched by name, not by its exact ARN. Identity Center
# creates it under a path IAM reserves for Identity Center, so no one can
# create a look-alike, and a recreated permission set, whose role gets a new
# generated suffix, cannot lock the owner out of the state that recreates it.

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

locals {
  # Who may touch the state at all. Root is the emergency path when Identity
  # Center is down (docs/owner-access.md#root-the-emergency-path).
  state_admin_principal_arns = [
    "arn:aws:iam::${local.account_id}:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_${module.owner_admin.permission_set_name}_*",
    "arn:aws:iam::${local.account_id}:root",
  ]

  state_bucket_resources = [
    aws_s3_bucket.state.arn,
    "${aws_s3_bucket.state.arn}/*",
  ]

  state_bucket_policy = {
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = local.state_bucket_resources
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
      {
        # Reading, writing, listing and reconfiguring alike, so no one outside
        # the list can replace this policy and undo it.
        Sid       = "DenyAllButTheOwner"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = local.state_bucket_resources
        Condition = {
          ArnNotLike = {
            "aws:PrincipalArn" = local.state_admin_principal_arns
          }
        }
      },
    ]
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode(local.state_bucket_policy)

  depends_on = [aws_s3_bucket_public_access_block.state]
}
