provider "aws" {
  region = local.region

  # Every resource carries the platform's tag set with Project = monitoring.
  # The stack's CI policies (monitoring/* and compute/*, foundation/ci-roles.tf)
  # scope EC2 by aws:RequestTag/Project and aws:ResourceTag/Project = monitoring,
  # so this block is load-bearing. Per-resource tags add Name and Component.
  default_tags {
    tags = module.context.tags
  }
}
