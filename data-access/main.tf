# The reconcile: binds and grants each agreed handshake on every dataset the
# foundation onboarded (datasets/). An edge exists only while the producer
# lists the consumer under the dataset's `consumers` and the consumer lists the
# dataset under its workspace's `reads`; `jwall-engineering-sites access
# render` derives the variables from datasets/ and every project's file. This
# stack creates bindings and grants only: the roles, credentials and locations
# are the foundation's, and each bucket policy is its producer's.

# Workspaces are named <project>-<environment>, environment prod.
data "databricks_mws_workspaces" "all" {
  provider = databricks.account
}

# Every external location in the metastore, seen through the host.
data "databricks_external_locations" "all" {
  provider = databricks.host
}

locals {
  workspace_ids = data.databricks_mws_workspaces.all.ids
  # The provider reports an empty list as null.
  locations = data.databricks_external_locations.all.names == null ? toset([]) : toset(data.databricks_external_locations.all.names)

  # A registry file merged before the foundation release that creates its
  # location has applied has nothing to bind yet: it waits, is reported, and
  # a later sweep binds it.
  ready               = { for key, d in var.datasets : key => d if contains(local.locations, d.location_name) }
  awaiting_onboarding = sort([for key, d in var.datasets : key if !contains(local.locations, d.location_name)])

  # A consumer whose workspace does not exist yet (its first Databricks apply
  # has not run) is left out the same way, never failing the others' run.
  missing = {
    for key, d in var.datasets : key => sort([
      for c in keys(d.consumers) : c if !contains(keys(local.workspace_ids), "${c}-prod")
    ])
  }
  missing_workspaces = { for key, consumers in local.missing : key => consumers if length(consumers) > 0 }

  bound = {
    for key, d in local.ready : key => {
      for c, v in d.consumers : c => {
        workspace_id     = local.workspace_ids["${c}-prod"]
        users_group_name = v.users_group_name
      } if contains(keys(local.workspace_ids), "${c}-prod")
    }
  }
}

# One instance per dataset with a location, even with no consumer left:
# revoking the last one destroys its grants and bindings, never the instance's
# absence leaving them behind.
module "access" {
  for_each  = local.ready
  source    = "jwallace145/jwall-engineering/aws//modules/databricks-dataset-access"
  version   = "0.24.0"
  providers = { databricks = databricks.host }

  external_location_name = each.value.location_name
  consumers              = local.bound[each.key]
}
