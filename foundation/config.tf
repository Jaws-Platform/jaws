# The tool configuration, the account it builds in, and every onboarded project.
#
# config/ at the repository root holds the tool configuration as several YAML
# files, read as one document: each file holds some of its top-level sections
# (config/README.md). This root builds in the account registry's primary account
# (config/aws.yaml), read here as `local.account`; the registry's other accounts
# are owner-access's, never this root's. Every project it gives roles, buckets
# and state prefixes to is an entry of config/projects.yaml (`local.registry`).

variable "config_path" {
  description = "The tool configuration: a directory of .yaml files, or one .yaml file holding every section. Null reads /etc/jaws/config when the hub's image has it, else config/ at the repository root; a caller passes JAWS_CONFIG (TF_VAR_config_path), the tests a fixture file."
  type        = string
  default     = null
}

variable "datasets_path" {
  description = "The onboarded datasets: the directory holding <owner>/<name>.yaml. Null reads the datasets/ beside the configuration (/etc/jaws/datasets in the hub's image, datasets/ at the repository root); a caller passes $JAWS_INFRA_ROOT/datasets (TF_VAR_datasets_path)."
  type        = string
  default     = null
}

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

  # The datasets/ beside the configuration, as the CLI reads them (jaws.access.infra_root).
  datasets_path = var.datasets_path != null ? var.datasets_path : "${dirname(trimsuffix(local.config_path, "/"))}/datasets"

  # The account this root builds in.
  primary_account = local.tool_config.aws.accounts[local.tool_config.aws.primary]

  # The sections that name things in the account.
  account = {
    aws = {
      account_id     = local.primary_account.account_id
      admin_role_arn = local.primary_account.admin_role_arn
    }
    context = local.tool_config.context
    state   = local.tool_config.state
    ecr     = local.tool_config.ecr
    # The names a platform leaves out follow its name root, as jaws.settings.databricks_defaults derives them
    databricks = merge({
      secret_parameter = "/${local.tool_config.context.name_root}/databricks/client-secret"
      metastore_name   = "${local.tool_config.context.name_root}-us-east-1"
      audit_bucket     = "${local.tool_config.context.name_root}-databricks-audit-logs"
    }, local.tool_config.databricks)
  }

  # Every onboarded project by its key, whichever GitHub owner it is under, with
  # its owner's ID and its repository as <owner>/<name>. projects.tf, bots.tf and
  # databricks.tf take the projects of their type from here.
  registry = merge([
    for owner, group in local.tool_config.projects : {
      for key, project in group.projects : key => merge(project, {
        owner      = owner
        owner_id   = group.owner_id
        repository = "${owner}/${project.repository}"
      })
    }
  ]...)
}

# The credentials must be the account's, or the plan stops here: applied with
# another account's credentials, this root would create its names there.
data "aws_caller_identity" "current" {
  lifecycle {
    # merge() would let a later file's section silently win; the CLI refuses the
    # same configuration (jaws.settings.load_document).
    precondition {
      condition     = length(flatten([for document in local.config_documents : keys(document)])) == length(keys(local.tool_config))
      error_message = "A section of the tool configuration is in two files of ${local.config_path}: each section lives in one."
    }

    # A missing directory reads as an empty registry, which would plan every onboarded dataset away.
    precondition {
      condition     = !(local.databricks_enabled && local.databricks_host_recorded) || fileexists("${local.datasets_path}/README.md")
      error_message = "The onboarded datasets are not at ${local.datasets_path} (no README.md there): planned without them, every onboarded dataset would be removed. Set datasets_path (TF_VAR_datasets_path), or keep datasets/ beside the configuration."
    }

    precondition {
      condition     = length(flatten([for group in values(local.tool_config.projects) : keys(group.projects)])) == length(keys(local.registry))
      error_message = "A project key is onboarded under two GitHub owners in config/projects.yaml: a key is unique across owners."
    }

    postcondition {
      condition     = self.account_id == local.account.aws.account_id
      error_message = "These credentials belong to account ${self.account_id}, but the primary account (config/aws.yaml) is ${local.account.aws.account_id}: use that account's credentials."
    }

    postcondition {
      condition     = can(regex("^arn:aws:iam::${local.account.aws.account_id}:role/", local.account.aws.admin_role_arn))
      error_message = "The primary account's admin_role_arn (config/aws.yaml) is not a role in ${local.account.aws.account_id}. Without it the hardened bucket policies would lock the owner out."
    }
  }
}
