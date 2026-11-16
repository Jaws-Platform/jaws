# Remote state in the shared bucket, under a prefix that no project's CI roles
# are listed for, so the bucket policy leaves it to the break-glass principals
# (foundation/state.tf). The bucket, key and region live in backend/prod.hcl:
#
#   terraform init -backend-config=backend/prod.hcl
terraform {
  backend "s3" {}
}
