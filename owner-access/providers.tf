provider "aws" {
  region = local.region

  # The organisation-wide tag set, as on the foundation stack. Of this stack's
  # resources only the permission set takes tags.
  default_tags {
    tags = module.context.tags
  }
}
