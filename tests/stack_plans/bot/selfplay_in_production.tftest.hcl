# braveheart-selfplay's live file in the production view, the first step of its
# move: the same task runner and an empty positions bucket under production's
# name. braveheart-trainer has no stack in production yet, so its GPU role is
# not a reader until it moves too; no Databricks share role, since Databricks is
# off in production.
mock_provider "aws" {
  source = "./tests/mocks"
}

run "plans_the_new_stack_and_its_positions_bucket" {
  command = plan

  assert {
    condition     = length(module.network) == 1 && length(module.tasks) == 1 && toset(keys(module.task_profiles)) == toset(["datagen", "relabel"])
    error_message = "the production stack has the same task runner and profiles"
  }

  assert {
    condition     = toset(keys(module.datasets)) == toset(["positions"]) && var.datasets[0].bucket == "jaws-braveheart-selfplay-positions" && var.datasets[0].prefix == "data/"
    error_message = "the production stack's positions bucket carries production's name"
  }

  assert {
    condition     = var.datasets[0].versioning && var.datasets[0].expire_noncurrent_days == null && length(var.datasets[0].expire_prefixes) == 0
    error_message = "the new bucket has the old one's retention: versioned, nothing expires"
  }

  assert {
    condition     = length(var.datasets[0].readers) == 0
    error_message = "no reader yet: the trainer has no stack in production, and Databricks is off there"
  }

  assert {
    condition     = var.tags["Organization"] == "jaws" && var.tags["ManagedBy"] == "jaws"
    error_message = "the production stack is stamped with production's organization"
  }
}
