# Remote state in this stack's own bucket in the management account, which
# the stack also manages (state.tf). The bucket, key and region live in
# backend/prod.hcl:
#
#   terraform init -backend-config=backend/prod.hcl
terraform {
  backend "s3" {}
}
