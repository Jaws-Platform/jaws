# Remote state beside owner-access's, in the management account's owner-only
# bucket (owner-access/state.tf): its policy denies every principal but the
# owner's Identity Center admin role and root, so no CI role can reach it. The
# bucket, key and region live in backend/prod.hcl:
#
#   terraform init -backend-config=backend/prod.hcl
terraform {
  backend "s3" {}
}
