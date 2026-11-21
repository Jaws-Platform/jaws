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
        "jaws-ds-braveheart-selfplay-positions",
      ]
    }
  }

  mock_data "databricks_catalogs" {
    defaults = {
      ids = ["braveheart_databricks", "braveheart_selfplay"]
    }
  }

  mock_data "databricks_schemas" {
    defaults = {
      ids = ["braveheart_selfplay.games", "braveheart_selfplay.positions"]
    }
  }

  mock_data "databricks_volumes" {
    defaults = {
      ids = ["braveheart_selfplay.games.files", "braveheart_selfplay.positions.files"]
    }
  }
}

variables {
  host_workspace_url = "https://dbc-01234567-89ab.cloud.databricks.com"
  fingerprint        = "0f5b6a3c9d8e7f60123456789abcdef0123456789abcdef0123456789abcdef0"
  owner_group_name   = "jaws-metastore-admins"
  datasets = {
    braveheart-selfplay-positions = {
      id              = "braveheart-selfplay/positions"
      location_name   = "jaws-ds-braveheart-selfplay-positions"
      credential_name = "jaws-ds-braveheart-selfplay-positions"
      catalog         = "braveheart_selfplay"
      schema          = "positions"
      volume          = "files"
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
        id              = "braveheart-selfplay/positions"
        location_name   = "jaws-ds-braveheart-selfplay-positions"
        credential_name = "jaws-ds-braveheart-selfplay-positions"
        catalog         = "braveheart_selfplay"
        schema          = "positions"
        volume          = "files"
        consumers       = {}
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

# The producer catalog: bound read-only to the union of the consumers of its
# ready datasets; each dataset's schema and volume granted to its own.

run "two_datasets_of_one_producer_with_different_consumers" {
  command = plan

  override_data {
    target = data.databricks_external_locations.all
    values = { names = ["jaws-ds-braveheart-selfplay-games", "jaws-ds-braveheart-selfplay-positions"] }
  }

  variables {
    datasets = {
      braveheart-selfplay-positions = {
        id              = "braveheart-selfplay/positions"
        location_name   = "jaws-ds-braveheart-selfplay-positions"
        credential_name = "jaws-ds-braveheart-selfplay-positions"
        catalog         = "braveheart_selfplay"
        schema          = "positions"
        volume          = "files"
        consumers = {
          braveheart-databricks = { users_group_name = "braveheart-databricks-workspace-users", purpose = "analysis" }
        }
      }
      braveheart-selfplay-games = {
        id              = "braveheart-selfplay/games"
        location_name   = "jaws-ds-braveheart-selfplay-games"
        credential_name = "jaws-ds-braveheart-selfplay-games"
        catalog         = "braveheart_selfplay"
        schema          = "games"
        volume          = "files"
        consumers = {
          databricks-poc = { users_group_name = "databricks-poc-workspace-users", purpose = "a demo" }
        }
      }
    }
  }

  assert {
    condition     = jsonencode(output.catalogs) == jsonencode({ braveheart_selfplay = ["braveheart-databricks", "databricks-poc"] })
    error_message = "the producer catalog is bound to the union of its datasets' consumers"
  }

  assert {
    condition = (jsonencode(keys(local.bound["braveheart-selfplay-positions"])) == jsonencode(["braveheart-databricks"])
    && jsonencode(keys(local.bound["braveheart-selfplay-games"])) == jsonencode(["databricks-poc"]))
    error_message = "each dataset's schema and volume are granted to its own consumers only"
  }
}

run "a_dataset_whose_catalog_or_schema_is_missing_waits" {
  command = plan

  override_data {
    target = data.databricks_catalogs.all
    values = { ids = ["braveheart_databricks"] }
  }

  assert {
    condition     = jsonencode(output.awaiting_onboarding) == jsonencode(["braveheart-selfplay-positions"]) && length(module.access) == 0 && length(module.catalog_access) == 0
    error_message = "a dataset whose producer catalog does not exist yet waits, binding and granting nothing"
  }
}

# The schema exists without its volume, as after release v0.42.1, whose apply
# created the schema and then failed on the volume: a sweep granting READ
# VOLUME then would fail, after the rest of its apply (the location's READ
# FILES revoked among it) had gone through.
run "a_dataset_whose_volume_is_missing_waits" {
  command = plan

  # How the provider reports an empty list of volumes.
  override_data {
    target = data.databricks_volumes.in
    values = { ids = null }
  }

  assert {
    condition     = jsonencode(output.awaiting_onboarding) == jsonencode(["braveheart-selfplay-positions"]) && length(module.access) == 0 && length(module.catalog_access) == 0
    error_message = "a dataset whose schema exists without its volume waits, binding and granting nothing"
  }
}

run "another_volume_in_the_schema_is_not_the_dataset" {
  command = plan

  override_data {
    target = data.databricks_volumes.in
    values = { ids = ["braveheart_selfplay.positions.scratch"] }
  }

  assert {
    condition     = jsonencode(output.awaiting_onboarding) == jsonencode(["braveheart-selfplay-positions"]) && length(module.access) == 0
    error_message = "only the dataset's own volume (files) makes it ready, not any volume in its schema"
  }
}

run "the_last_edge_into_a_producer_unbinds_its_catalog" {
  command = plan

  variables {
    datasets = {
      braveheart-selfplay-positions = {
        id              = "braveheart-selfplay/positions"
        location_name   = "jaws-ds-braveheart-selfplay-positions"
        credential_name = "jaws-ds-braveheart-selfplay-positions"
        catalog         = "braveheart_selfplay"
        schema          = "positions"
        volume          = "files"
        consumers       = {}
      }
    }
  }

  assert {
    condition     = jsonencode(output.catalogs) == jsonencode({ braveheart_selfplay = [] })
    error_message = "with no consumer left, the catalog stays managed with no binding and no consumer's USE CATALOG"
  }
}
