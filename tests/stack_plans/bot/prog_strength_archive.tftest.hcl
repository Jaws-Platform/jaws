# prog-strength-archive's live file in the production view: the cold archive of
# the deprecated Prog Strength, a dataset and nothing else. No task runner, so no
# VPC, and nothing automated writes or reads the bucket: the owner uploads it once
# with admin credentials.
mock_provider "aws" {
  source = "./tests/mocks"
}

run "plans_one_bucket_and_nothing_else" {
  command = plan

  assert {
    condition     = toset(keys(module.datasets)) == toset(["backups"]) && var.datasets[0].bucket == "jaws-prog-strength-archive-backups" && var.datasets[0].prefix == "data/"
    error_message = "the one dataset is planned under production's name"
  }

  assert {
    condition     = var.datasets[0].versioning && var.datasets[0].expire_noncurrent_days == null && length(var.datasets[0].expire_prefixes) == 0
    error_message = "the bucket is versioned and nothing in it expires"
  }

  assert {
    condition     = length(var.datasets[0].readers) == 0 && length(var.datasets[0].writers) == 0
    error_message = "no role is granted the bucket: only the owner's admin credentials reach it"
  }

  assert {
    condition     = length(module.network) == 0 && length(module.tasks) == 0 && length(module.task_results) == 0 && length(module.task_profiles) == 0
    error_message = "a dataset alone creates no VPC and no task resources"
  }

  assert {
    condition     = length(module.image) == 0 && length(module.bot) == 0 && length(module.records) == 0
    error_message = "a research project has no image repository, instance or records bucket"
  }

  assert {
    condition     = var.tags["Organization"] == "jaws" && var.tags["ManagedBy"] == "jaws" && var.tags["Project"] == "prog-strength-archive" && var.tags["Repository"] == "Prog-Strength/prog-strength-archive"
    error_message = "the stack is stamped with production's organization and the archive's repository"
  }
}
