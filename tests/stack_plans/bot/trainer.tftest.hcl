# braveheart-trainer's live file (tests/fixtures/registry/): a task runner, and the
# nets bucket the split copies data/nets/ into.
mock_provider "aws" {
  source = "./tests/mocks"
}

run "plans_a_task_runner_and_the_nets_bucket" {
  command = plan

  assert {
    condition     = !var.bot_enabled && length(module.bot) == 0 && length(module.image) == 0 && length(module.records) == 0
    error_message = "a research project has no bot, image repository or records bucket"
  }

  assert {
    condition     = length(module.network) == 1 && length(module.tasks) == 1 && length(module.task_results) == 1
    error_message = "braveheart-trainer has a network, a task runner and a results bucket"
  }

  assert {
    condition     = toset(keys(module.task_profiles)) == toset(["gpu"])
    error_message = "braveheart-trainer has one launch template per task profile"
  }

  assert {
    condition     = toset(keys(module.datasets)) == toset(["nets"]) && var.datasets[0].bucket == "jaws-braveheart-trainer-nets" && var.datasets[0].prefix == "data/"
    error_message = "braveheart-trainer has one dataset, nets, under data/ like the bucket it is copied from"
  }

  assert {
    condition     = var.datasets[0].versioning && var.datasets[0].expire_noncurrent_days == null && length(var.datasets[0].expire_prefixes) == 0
    error_message = "the nets are versioned and nothing expires"
  }

  assert {
    condition     = length(var.datasets[0].writers) == 0
    error_message = "no task instance writes the whole prefix: only the GPU profile adds objects, under its grant"
  }

  assert {
    condition     = jsonencode(var.datasets[0].readers) == jsonencode(["arn:aws:iam::570327089884:role/jaws-braveheart-selfplay-task-relabel"])
    error_message = "self-play's relabel tasks, and only they, read the nets through the bucket policy"
  }

  assert {
    condition     = jsonencode([for p in var.task_profiles : p.datasets if p.name == "gpu"][0]) == jsonencode([{ name = "nets", read = [], write = ["nets/"], write_once = [] }])
    error_message = "the GPU profile writes nets/ and reads nothing of its own bucket; the positions come from self-play's readers"
  }
}
