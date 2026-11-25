# The production account, with the owner's own credentials (the jaws-prod
# profile): never a CI role's. The plan stops on any other account (main.tf).
provider "aws" {
  # ECR Public's API is in us-east-1 only.
  region = "us-east-1"

  # Jaws's own tags: Project = jaws.
  default_tags {
    tags = module.context.tags
  }
}
