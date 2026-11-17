# Remote state in S3 with native lockfile locking (no DynamoDB).
#
# The block is intentionally empty: the bucket, key and region live in
# backend/<account>.hcl (management.hcl or production.hcl) and are passed with
#
#   terraform init -backend-config=backend/management.hcl
#
# Key convention for every jwall-engineering stack:
#   project=<project>/env=<env>/<project>-<env>.tfstate
#
# During bootstrap the state bucket does not exist yet, so the first apply runs
# against local state through a gitignored override file. See README.md.
terraform {
  backend "s3" {}
}
