# The tool configuration, read as the foundation reads it (foundation/config.tf):
# the configuration directory (/etc/jaws/config in the hub's image, else config/ at the repository root), several YAML files read as one document. This
# stack builds in the account registry's primary account (config/aws.yaml), from
# the `monitoring` section of config/monitoring.yaml; the CLI validates that
# section (jaws.settings.MonitoringSection) and this root reads it as written,
# with the same defaults for the keys it may leave out.

locals {
  # Where the hub's image keeps the configuration, as the CLI looks (jaws.settings.IMAGE_CONFIG_PATH).
  image_config_path = "/etc/jaws/config"
  in_image          = length(fileset(local.image_config_path, "*.yaml")) > 0
  config_path       = var.config_path != null ? var.config_path : local.in_image ? local.image_config_path : "${path.module}/../config"
  config_files = endswith(local.config_path, ".yaml") ? [local.config_path] : [
    for name in sort(fileset(local.config_path, "*.yaml")) : "${local.config_path}/${name}"
  ]
  config_documents = [for config_file in local.config_files : yamldecode(file(config_file))]
  tool_config      = merge(local.config_documents...)

  region     = "us-east-1"
  account_id = local.tool_config.aws.accounts[local.tool_config.aws.primary].account_id
  name_root  = local.tool_config.context.name_root

  # Null: the platform is off, and this stack plans nothing.
  monitoring  = try(local.tool_config.monitoring, null)
  cost_config = try(local.monitoring.cost, null)

  # Every onboarded project by its key, whichever GitHub owner it is under.
  registry = merge([
    for owner, group in local.tool_config.projects : {
      for key, project in group.projects : key => project
    }
  ]...)
}

# The stack's identity and tags, from the library's context module like every
# jaws stack's (docs/tagging.md): Project is monitoring, the project its CI
# roles are scoped to.
module "context" {
  source  = "Jaws-Platform/jaws-foundation/aws//modules/context"
  version = "0.2.0"

  project      = "monitoring"
  environment  = "prod"
  repository   = "Jaws-Platform/jaws"
  owner        = local.tool_config.context.owner
  organization = local.tool_config.context.organization
  name_root    = local.name_root
  managed_by   = local.tool_config.context.managed_by
}

# The credentials must be the primary account's, or the plan stops here.
# tflint-ignore: terraform_unused_declarations # read for its conditions alone
data "aws_caller_identity" "current" {
  lifecycle {
    # merge() would let a later file's section silently win; the CLI refuses the
    # same configuration (jaws.settings.load_document).
    precondition {
      condition     = length(flatten([for document in local.config_documents : keys(document)])) == length(keys(local.tool_config))
      error_message = "A section of the tool configuration is in two files of ${local.config_path}: each section lives in one."
    }

    # The root module always runs the normalizer, which reads the billing
    # bucket. A host-only node (no monitoring.cost) is not built by this stack.
    precondition {
      condition     = local.monitoring == null || local.cost_config != null
      error_message = "config/monitoring.yaml sets monitoring without monitoring.cost: the monitoring stack reads the foundation's billing bucket, so set monitoring.cost (or leave out monitoring)."
    }

    postcondition {
      condition     = self.account_id == local.account_id
      error_message = "These credentials belong to account ${self.account_id}, but the primary account (config/aws.yaml) is ${local.account_id}: use that account's credentials."
    }
  }
}
