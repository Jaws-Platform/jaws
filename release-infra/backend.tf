# Remote state in the platform's shared state bucket, under its own prefix
# (project=release-infra/). No CI role is granted that prefix: IAM keeps them
# out of it, and of the CI roles, the bucket policy exempts only the foundation's
# apply role. The bucket, key and region live in backend/prod.hcl:
#
#   terraform init -backend-config=backend/prod.hcl
terraform {
  backend "s3" {}
}
