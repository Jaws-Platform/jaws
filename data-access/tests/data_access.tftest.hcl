# The reconcile binds each agreed edge, and only those. Mock Databricks data
# stands in for the account's workspaces and the host's external locations.
# A run block cannot address resources inside a child module, so these assert
# the module instances, what each is given (local.bound) and the outputs; the
# library's own test (databricks-dataset-access) pins one binding per consumer
# and one authoritative grants resource per location.

mock_provider "databricks" {
  alias = "account"

  mock_data "databricks_mws_workspaces" {
    defaults = {
      ids = {
        "braveheart-databricks-prod" = 1111111111111111
        "databricks-poc-prod"        = 2222222222222222
      }
    }
  }
}

mock_provider "databricks" {
  alias = "host"

  mock_data "databricks_external_locations" {
    defaults = {
      names = [
        "braveheart-databricks-catalog",
        "jwall-engineering-ds-braveheart-selfplay-positions",
      ]
    }
  }
}

variables {
  host_workspace_url = "https://dbc-01234567-89ab.cloud.databricks.com"
  fingerprint        = "0f5b6a3c9d8e7f60123456789abcdef0123456789abcdef0123456789abcdef0"
  datasets = {
    braveheart-selfplay-positions = {
      id            = "braveheart-selfplay/positions"
      location_name = "jwall-engineering-ds-braveheart-selfplay-positions"
      consumers = {
        braveheart-databricks = {
          users_group_name = "braveheart-databricks-workspace-users"
          purpose          = "generation-over-generation self-play analysis"
        }
        databricks-poc = {
          users_group_name = "databricks-poc-workspace-users"
          purpose          = "a second reader"
        }
      }
    }
  }
}

run "two_consumers_are_bound_through_one_module_instance" {
  command = plan

  assert {
    condition     = length(module.access) == 1
    error_message = "one onboarded dataset with a location must be one module instance."
  }

  assert {
    condition = jsonencode(local.bound) == jsonencode({
      braveheart-selfplay-positions = {
        braveheart-databricks = { users_group_name = "braveheart-databricks-workspace-users", workspace_id = 1111111111111111 }
        databricks-poc        = { users_group_name = "databricks-poc-workspace-users", workspace_id = 2222222222222222 }
      }
    })
    error_message = "each consumer must be bound by its <project>-prod workspace ID, with its users group."
  }

  assert {
    condition     = jsonencode(output.edges) == jsonencode({ braveheart-selfplay-positions = ["braveheart-databricks", "databricks-poc"] })
    error_message = "edges must list both bound consumers, sorted."
  }

  assert {
    condition     = length(output.awaiting_onboarding) == 0 && length(output.missing_workspaces) == 0
    error_message = "nothing waits when the location and both workspaces exist."
  }

  assert {
    condition     = output.fingerprint == var.fingerprint
    error_message = "the fingerprint output must be the applied variables' fingerprint."
  }
}

run "a_dataset_without_a_location_waits_and_is_reported" {
  command = plan

  override_data {
    target = data.databricks_external_locations.all
    values = { names = ["braveheart-databricks-catalog"] }
  }

  assert {
    condition     = length(module.access) == 0
    error_message = "a dataset whose location does not exist yet must create no module instance."
  }

  assert {
    condition     = jsonencode(output.awaiting_onboarding) == jsonencode(["braveheart-selfplay-positions"])
    error_message = "a dataset whose location does not exist yet must be reported under awaiting_onboarding."
  }

  assert {
    condition     = length(output.edges) == 0
    error_message = "nothing is bound to a location that does not exist."
  }
}

run "a_host_that_lists_no_location_reports_every_dataset_as_waiting" {
  command = plan

  # How the provider reports an empty list of locations.
  override_data {
    target = data.databricks_external_locations.all
    values = { names = null }
  }

  assert {
    condition     = jsonencode(output.awaiting_onboarding) == jsonencode(["braveheart-selfplay-positions"])
    error_message = "a host that lists no location must report every dataset as awaiting onboarding, not fail."
  }

  assert {
    condition     = length(module.access) == 0
    error_message = "nothing is bound when no location exists."
  }
}

run "a_consumer_without_a_workspace_is_left_out_and_reported" {
  command = plan

  override_data {
    target = data.databricks_mws_workspaces.all
    values = { ids = { "braveheart-databricks-prod" = 1111111111111111 } }
  }

  assert {
    condition     = jsonencode(output.edges) == jsonencode({ braveheart-selfplay-positions = ["braveheart-databricks"] })
    error_message = "the consumer that has a workspace must still be bound."
  }

  assert {
    condition     = jsonencode(output.missing_workspaces) == jsonencode({ braveheart-selfplay-positions = ["databricks-poc"] })
    error_message = "a consumer with no <project>-prod workspace must be reported under missing_workspaces."
  }
}

run "a_dataset_nobody_reads_keeps_its_instance_and_binds_nothing" {
  command = plan

  variables {
    datasets = {
      braveheart-selfplay-positions = {
        id            = "braveheart-selfplay/positions"
        location_name = "jwall-engineering-ds-braveheart-selfplay-positions"
        consumers     = {}
      }
    }
  }

  # Revoking the last consumer empties the instance (its grants and bindings
  # are destroyed) rather than leaving them behind.
  assert {
    condition     = jsonencode(output.edges) == jsonencode({ braveheart-selfplay-positions = [] })
    error_message = "a dataset with no agreed consumer must bind and grant nothing."
  }
}

run "a_fingerprint_that_is_not_a_digest_is_refused" {
  command = plan

  variables {
    fingerprint = "not-a-digest"
  }

  expect_failures = [var.fingerprint]
}

run "a_host_url_that_is_not_a_databricks_workspace_is_refused" {
  command = plan

  variables {
    host_workspace_url = "http://dbc-01234567-89ab.cloud.databricks.com"
  }

  expect_failures = [var.host_workspace_url]
}
