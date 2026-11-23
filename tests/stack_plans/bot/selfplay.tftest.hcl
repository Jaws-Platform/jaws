# braveheart-selfplay's live file (tests/fixtures/registry/): a task runner, and the
# positions bucket the split copies data/selfplay/ into.
mock_provider "aws" {
  source = "./tests/mocks"
}

run "plans_a_task_runner_and_the_positions_bucket" {
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
    condition     = toset(keys(module.datasets)) == toset(["positions"]) && var.datasets[0].bucket == "jaws-braveheart-selfplay-positions" && var.datasets[0].prefix == "data/"
    error_message = "braveheart-selfplay has one dataset, positions, under data/ like the bucket it is copied from"
  }

  assert {
    condition     = var.datasets[0].versioning && var.datasets[0].expire_noncurrent_days == null && length(var.datasets[0].expire_prefixes) == 0
    error_message = "the positions are versioned and nothing expires"
  }

  assert {
    condition     = length(var.datasets[0].writers) == 0
    error_message = "no task instance writes the whole prefix: only the datagen and relabel profiles add objects, under their grants"
  }

  assert {
    condition = jsonencode(var.datasets[0].readers) == jsonencode([
      "arn:aws:iam::222222222222:role/jaws-braveheart-trainer-task-gpu",
      "arn:aws:iam::222222222222:role/jaws-ds-braveheart-selfplay-positions",
    ])
    error_message = "the trainer's GPU tasks and the onboarded dataset's role (an agreed handshake with braveheart-databricks), and only they, read the positions through the bucket policy"
  }

  # jsonencode: a list(...) variable never equals a tuple literal with `==`.
  assert {
    condition = (
      jsonencode([for p in var.task_profiles : p.datasets if p.name == "datagen"][0]) == jsonencode([{ name = "positions", read = [], write = ["selfplay/"], write_once = [] }]) &&
      jsonencode([for p in var.task_profiles : p.datasets if p.name == "relabel"][0]) == jsonencode([{ name = "positions", read = ["selfplay/"], write = ["selfplay/relabel/"], write_once = [] }])
    )
    error_message = "datagen writes selfplay/; relabel reads selfplay/ and writes selfplay/relabel/"
  }
}
