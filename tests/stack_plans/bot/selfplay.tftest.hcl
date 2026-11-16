# braveheart-selfplay's live file (tests/fixtures/registry/): a task runner and, until the data
# moves, no dataset.
mock_provider "aws" {
  source = "./tests/mocks"
}

run "plans_a_task_runner_that_can_reach_no_dataset" {
  command = plan

  assert {
    condition     = !var.bot_enabled && length(module.bot) == 0 && length(module.image) == 0 && length(module.records) == 0
    error_message = "a research project has no bot, image repository or records bucket"
  }

  assert {
    condition     = length(module.network) == 1 && length(module.tasks) == 1 && length(module.task_results) == 1
    error_message = "braveheart-selfplay has a network, a task runner and a results bucket"
  }

  assert {
    condition     = toset(keys(module.task_profiles)) == toset(["datagen", "relabel"])
    error_message = "braveheart-selfplay has one launch template per task profile"
  }

  assert {
    condition     = length(var.datasets) == 0 && length(module.datasets) == 0
    error_message = "until the data moves, braveheart-selfplay has no dataset, so its tasks can write nowhere"
  }

  assert {
    condition     = alltrue([for p in var.task_profiles : length(p.datasets) == 0])
    error_message = "no task profile is granted a dataset"
  }
}
