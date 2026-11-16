# Remote state in S3 with native lockfile locking, as every jwall-engineering
# stack: the bucket, key and region live in backend/prod.hcl and are passed with
#
#   terraform init -backend-config=backend/prod.hcl
terraform {
  backend "s3" {}
}
