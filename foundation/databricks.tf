# The Databricks account resources this stack owns, and the CI roles of the
# Databricks workspace projects (config.yaml `databricks`, and
# `projects.<key>.databricks` for each project's guardrails).
#
# Account resources, one of each for the whole account:
#
#   the us-east-1 Unity Catalog metastore   every workspace in the region shares it
#   audit log delivery                      jwall-engineering-databricks-audit-logs, audit/
#
# They wait for config.yaml `databricks.enabled`. While it is false (the
# owner has not created the service principal yet) they are not planned, so
# the foundation plan needs no Databricks credential and the databricks
# provider makes no call. The workflows put the credential in the
# environment only when it is true (scripts/databricks-credentials.sh).
#
# The client secret is NOT created here: the owner writes the SSM parameter
# with `jaws databricks credentials set`, so it is in no
# Terraform state. This stack only builds its ARN for the CI policies.
#
# The registry of Databricks workspace projects (a project file whose only
# component is a databricks-workspace). Each entry gets two CI roles:
#
#   jwall-engineering-<key>-ci-plan   trusted for pull_request on THIS repo     tfstate/read, compute/read, databricks/read
#   jwall-engineering-<key>-ci-apply  trusted for environment:prod on THIS repo tfstate/write, compute/read, compute/manage,
#                                                                               databricks/read, databricks/manage
#
# and no release or task role. Like a bot's, the project's stacks are planned
# and applied from this repository (ci.yml databricks-plan,
# databricks-apply.yml). Both stacks' state (account and workspace) lives
# under project=<key>/ in the shared bucket (state.tf).

locals {
  databricks = local.account.databricks

  databricks_enabled = local.databricks.enabled

  # The one parameter holding the service principal's client secret, and the
  # event-log prefix in the audit bucket (each project appends under
  # <events_prefix>project=<key>/).
  databricks_secret_parameter_arn = "arn:aws:ssm:${local.region}:${local.account_id}:parameter/${trimprefix(local.databricks.secret_parameter, "/")}"
  databricks_events_arn_prefix    = "arn:aws:s3:::${local.databricks.audit_bucket}/${trimsuffix(local.databricks.events_prefix, "/")}/"

  # repository_id: gh api repos/<owner>/<repo> --jq .id
  # owner_id:      gh api repos/<owner>/<repo> --jq .owner.id. A deployer's
  #                federation subject names both (docs/databricks.md).
  # One line per entry, as in bots.tf (the workflows read this block).
  databricks_projects = {
    braveheart-databricks = { repository = "Braveheart-Chess/braveheart-databricks", repository_id = "1458504699", owner_id = "356866252" }
  }

  databricks_ci = {
    for key, project in local.served_databricks_projects : key => {
      tfstate = {
        bucket_arn = module.state_bucket.arn
        prefix     = "project=${key}/"
      }
      databricks = {
        secret_parameter_arn = local.databricks_secret_parameter_arn
        events_object_arn    = "${local.databricks_events_arn_prefix}project=${key}/*"
      }
    }
  }
}

# The config.yaml placeholders must be filled in before `enabled` turns the
# account resources on: the metastore module would make the @example.com
# addresses its admins, and the nil UUID is no account or service principal.
# A failed precondition fails the plan, so nothing is applied. Not planned
# while disabled (the placeholders are expected then). The CLI's settings
# validation refuses the same config.yaml.
locals {
  databricks_nil_uuid = "00000000-0000-0000-0000-000000000000"
  databricks_placeholder_admins = [
    for email in local.databricks.metastore_admins : email
    if endswith(lower(email), "@example.com")
  ]
}

resource "terraform_data" "databricks_config_filled_in" {
  count = local.databricks_enabled ? 1 : 0

  lifecycle {
    precondition {
      condition     = lower(local.databricks.account_id) != local.databricks_nil_uuid
      error_message = "config.yaml databricks.account_id is still the nil UUID placeholder: fill in the Databricks account ID (or set databricks.enabled back to false)."
    }

    precondition {
      condition     = lower(local.databricks.client_id) != local.databricks_nil_uuid
      error_message = "config.yaml databricks.client_id is still the nil UUID placeholder: fill in the service principal's application (client) ID (or set databricks.enabled back to false)."
    }

    precondition {
      condition     = length(local.databricks_placeholder_admins) == 0
      error_message = "config.yaml databricks.metastore_admins still holds the placeholder ${join(", ", local.databricks_placeholder_admins)}: replace it with the owner's real email (an account user) before the foundation makes it a metastore admin."
    }
  }
}

module "databricks_metastore" {
  count     = local.databricks_enabled ? 1 : 0
  source    = "jwallace145/jwall-engineering/aws//modules/databricks-metastore"
  version   = "0.28.0"
  providers = { databricks = databricks.account }

  name                             = local.databricks.metastore_name
  admin_group_name                 = "${local.context.organization}-metastore-admins" # as access.py names it
  admin_user_names                 = local.databricks.metastore_admins
  service_principal_application_id = local.databricks.client_id
}

module "databricks_audit_logs" {
  count     = local.databricks_enabled ? 1 : 0
  source    = "jwallace145/jwall-engineering/aws//modules/databricks-audit-logs"
  version   = "0.28.0"
  providers = { aws = aws, databricks = databricks.account }

  account_id  = local.databricks.account_id
  bucket_name = local.databricks.audit_bucket
  role_name   = local.databricks_log_delivery_role_name
}

# The shared-objects host: a serverless workspace with no VPC, NAT, buckets,
# catalog or users, so metastore-level objects that need a workspace to be
# created through but belong to no project (onboarded datasets, below, and
# their bindings in data-access/) have a home. Only the metastore admin group is
# assigned to it. It has no standing AWS cost.
module "databricks_shared_host" {
  count     = local.databricks_enabled ? 1 : 0
  source    = "jwallace145/jwall-engineering/aws//modules/databricks-host-workspace"
  version   = "0.28.0"
  providers = { databricks = databricks.account }

  account_id       = local.databricks.account_id
  workspace_name   = local.databricks_host_name
  metastore_id     = module.databricks_metastore[0].metastore_id
  admin_group_name = module.databricks_metastore[0].admin_group_name

  tags = merge(module.context.tags, {
    CostCenter = local.account.context.managed_by
    Workspace  = local.databricks_host_name
  })

  # The module looks the admin group up by name. In a fresh account the group
  # is created in the same apply, so the lookup waits for it: data sources in
  # this module are read at apply whenever the metastore module has changes.
  depends_on = [module.databricks_metastore]
}

# --------------------------------------------------- onboarded datasets

# Each file under datasets/ (datasets/<owner>/<name>.yaml) onboards one dataset:
# one read-only role, storage credential and external location, all named
# <organization>-ds-<owner>-<name>, created through the host and bound to it
# only. Onboarding grants nothing: the role reads only once the owner's bucket
# policy names it (the owner's Bot apply, for an agreed handshake), and a
# workspace is bound and granted only by the data-access stack (data-access/).
# Names match access.py's load_registry (registry/, tested against the same
# expected output).
module "dataset_registry" {
  source = "./registry"

  directory    = "${path.module}/../datasets"
  organization = local.context.organization

  # Each workspace's own catalog is <project> with - replaced by _.
  reserved_catalogs = [for p in keys(local.databricks_projects) : replace(p, "-", "_")]

  # The live overlap check below: what the host lists, then each location's URL.
  live_location_names = length(data.databricks_external_locations.all) > 0 ? data.databricks_external_locations.all[0].names : null
  live_location_urls  = { for name, l in data.databricks_external_location.live : name => l.external_location_info[0].url }
}

locals {
  # The host is named for the account: jwall-engineering-shared in management,
  # jaws-shared in production. So is the audit log delivery's role and its
  # Databricks credential (the library's default is management's name).
  databricks_host_name              = "${local.context.organization}-shared"
  databricks_log_delivery_role_name = "${local.context.organization}-databricks-log-delivery"

  # Datasets are onboarded through the host, whose URL configures their
  # provider, so an account builds Databricks in two applies: the host first,
  # then the datasets once config.yaml records the host's URL
  # (databricks.shared_host_url; production's override is null until then).
  databricks_host_recorded = try(local.databricks.shared_host_url, null) != null

  onboarded_datasets = local.databricks_enabled && local.databricks_host_recorded ? module.dataset_registry.datasets : {}

  # One catalog per producer with an onboarded dataset: catalog => producer.
  producer_catalogs = { for c, owners in { for d in values(local.onboarded_datasets) : d.catalog => d.owner... } : c => owners[0] }
}

# The producer catalogs' managed storage (databricks-catalog-storage): the
# metastore has no storage root, so each producer catalog's managed location
# is a prefix of this one bucket. Nothing is ever written there.
module "dataset_catalog_storage" {
  count     = local.databricks_enabled && local.databricks_host_recorded ? 1 : 0
  source    = "jwallace145/jwall-engineering/aws//modules/databricks-catalog-storage"
  version   = "0.28.0"
  providers = { aws = aws, databricks = databricks.shared }

  name              = "${local.context.organization}-dataset-catalogs"
  host_workspace_id = module.databricks_shared_host[0].workspace_id
  owner_group_name  = module.databricks_metastore[0].admin_group_name
  apply_role_arn    = module.infra_ci_apply.role_arn
}

# One isolated catalog per producer, owned by the platform, bound read-write
# to the host only; each of its onboarded datasets is a schema there holding
# an external volume `files`. Consumers are bound read-only, and granted, by
# the data-access reconcile (data-access/).
module "producer_catalog" {
  for_each  = local.producer_catalogs
  source    = "jwallace145/jwall-engineering/aws//modules/databricks-producer-catalog"
  version   = "0.28.0"
  providers = { databricks = databricks.shared }

  producer          = each.value
  storage_url       = module.dataset_catalog_storage[0].url
  host_workspace_id = module.databricks_shared_host[0].workspace_id
  owner_group_name  = module.databricks_metastore[0].admin_group_name

  # The storage's url output is built from its name, so it carries no
  # dependency: without this, a catalog is created before the external
  # location its managed storage lies under, and Unity Catalog refuses it
  # ("External Location ... does not exist", the v0.42.0 release apply).
  depends_on = [module.dataset_catalog_storage]
}

# Unity Catalog refuses overlapping external locations in the metastore, and
# the registry cannot see the ones it did not create (a location made by hand,
# a share being retired). So every registry URL is checked against every other
# location the host lists (registry/ computes which to read and which overlap;
# the provider reports none as null). Locations bound only to other workspaces,
# such as each workspace's catalog, may be invisible here: Unity Catalog still
# refuses an overlap with them at apply, later and less clearly.
data "databricks_external_locations" "all" {
  count    = length(local.onboarded_datasets) > 0 ? 1 : 0
  provider = databricks.shared
}

data "databricks_external_location" "live" {
  for_each = length(local.onboarded_datasets) > 0 ? module.dataset_registry.live_names_to_check : toset([])
  provider = databricks.shared

  name = each.key
}

resource "terraform_data" "dataset_overlap_check" {
  count = length(local.onboarded_datasets) > 0 ? 1 : 0

  lifecycle {
    precondition {
      condition     = length(module.dataset_registry.overlaps) == 0
      error_message = "An onboarded dataset overlaps a location already in the metastore, which Unity Catalog refuses: ${join("; ", module.dataset_registry.overlaps)}. Retire the other location first, or onboard another prefix."
    }
  }
}

module "databricks_dataset" {
  for_each  = local.onboarded_datasets
  source    = "jwallace145/jwall-engineering/aws//modules/databricks-dataset"
  version   = "0.28.0"
  providers = { aws = aws, databricks = databricks.shared }

  name              = each.value.platform_name
  bucket            = each.value.bucket
  prefix            = each.value.prefix
  host_workspace_id = module.databricks_shared_host[0].workspace_id
  owner_group_name  = module.databricks_metastore[0].admin_group_name

  # The dataset's schema and files volume in its producer's catalog.
  catalog_name = module.producer_catalog[each.value.catalog].catalog_name
  schema_name  = each.value.schema

  depends_on = [terraform_data.dataset_overlap_check]
}

# config.yaml names the host's URL for the data-access stack; Databricks picked
# it when this stack created the host. A mismatch is reported, not fatal. So is
# a URL not recorded yet: the datasets wait for it (above).
check "shared_host_url" {
  assert {
    condition     = !local.databricks_enabled || try(local.databricks.shared_host_url, null) == try(module.databricks_shared_host[0].workspace_url, null)
    error_message = "config.yaml databricks.shared_host_url must be the shared host's URL (output databricks_shared_host.workspace_url) for this account: the datasets are onboarded, and the data-access stack binds and grants, only once it is recorded."
  }
}

module "databricks_ci_plan" {
  for_each = local.served_databricks_projects
  source   = "jwallace145/jwall-engineering/aws//modules/ci-plan-role"
  version  = "0.28.0"

  project            = each.key
  name_root          = local.context.organization
  repository         = local.context.repository
  repository_aliases = local.context.repository_aliases
  owner_id           = local.github.owner_id
  repository_id      = local.github.repository_id
  oidc_provider_arn  = data.aws_iam_openid_connect_provider.github.arn

  policies = ["tfstate/read", "compute/read", "databricks/read"]

  policy_inputs = {
    tfstate    = local.databricks_ci[each.key].tfstate
    databricks = local.databricks_ci[each.key].databricks
  }
}

module "databricks_ci_apply" {
  for_each = local.served_databricks_projects
  source   = "jwallace145/jwall-engineering/aws//modules/ci-apply-role"
  version  = "0.28.0"

  project            = each.key
  name_root          = local.context.organization
  repository         = local.context.repository
  repository_aliases = local.context.repository_aliases
  owner_id           = local.github.owner_id
  repository_id      = local.github.repository_id
  oidc_provider_arn  = data.aws_iam_openid_connect_provider.github.arn
  environment        = "prod"

  policies = ["tfstate/write", "compute/read", "compute/manage", "databricks/read", "databricks/manage"]

  policy_inputs = {
    tfstate    = local.databricks_ci[each.key].tfstate
    databricks = local.databricks_ci[each.key].databricks
  }
}

# A registered project without its central guardrails would get roles but no
# network range or compute policies; one that is also a site or a bot would
# share (and overwrite) that project's state prefix entry in state.tf.
check "databricks_projects_have_guardrails" {
  assert {
    condition = alltrue([
      for key in keys(local.databricks_projects) :
      try(local.tool_config.projects[key].databricks, null) != null
    ])
    error_message = "Every entry of local.databricks_projects needs a projects.<key>.databricks entry in config.yaml."
  }

  assert {
    condition     = length(setintersection(keys(local.databricks_projects), concat(keys(local.bots), keys(local.projects)))) == 0
    error_message = "A Databricks project must not also be a site or a bot: they would share the project=<key>/ state prefix."
  }
}
