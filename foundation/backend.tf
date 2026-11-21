# Remote state in S3 with native lockfile locking (no DynamoDB).
#
# The block is intentionally empty: the bucket, key and region live in
# backend/prod.hcl and are passed with
#
#   terraform init -backend-config=backend/prod.hcl
#
# Key convention for every jaws stack:
#   project=<project>/env=<env>/<project>-<env>.tfstate
#
terraform {
  backend "s3" {}
}
