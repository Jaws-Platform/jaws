# braveheart-trainer's live file in the production view, the second step of the
# two projects' move: the same task runner and GPU profile, and an empty nets
# bucket under production's name. braveheart-selfplay already has a stack in
# production, so its relabel role there is the reader.
mock_provider "aws" {
  source = "./tests/mocks"
}

run "plans_the_new_stack_and_its_nets_bucket" {
  command = plan

  assert {
    condition     = length(module.network) == 1 && length(module.tasks) == 1 && toset(keys(module.task_profiles)) == toset(["gpu"])
    error_message = "the production stack has the same task runner and GPU profile"
  }

  assert {
    condition     = toset(keys(module.datasets)) == toset(["nets"]) && var.datasets[0].bucket == "jaws-braveheart-trainer-nets" && var.datasets[0].prefix == "data/"
    error_message = "the production stack's nets bucket carries production's name"
  }

  assert {
    condition     = var.datasets[0].versioning && var.datasets[0].expire_noncurrent_days == null && length(var.datasets[0].expire_prefixes) == 0
    error_message = "the new bucket has the old one's retention: versioned, nothing expires"
  }

  assert {
    condition     = jsonencode(var.datasets[0].readers) == jsonencode(["arn:aws:iam::570327089884:role/jaws-braveheart-selfplay-task-relabel"])
    error_message = "self-play's production relabel role, and only it, reads the nets: no management role and no admin"
  }

  assert {
    condition     = var.tags["Organization"] == "jaws" && var.tags["ManagedBy"] == "jaws"
    error_message = "the production stack is stamped with production's organization"
  }
}
