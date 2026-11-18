# braveheart-selfplay's live file in the management view while it moves to
# production: its old stack, unchanged except that the positions bucket lets
# production's admin role read it, for the owner's server-side copy
# (docs/datasets.md, "Moving a dataset project to production").
mock_provider "aws" {
  source = "./tests/mocks"
}

run "the_old_positions_bucket_admits_the_copy" {
  command = plan

  assert {
    condition     = toset(keys(module.datasets)) == toset(["positions"]) && var.datasets[0].bucket == "jwall-engineering-braveheart-selfplay-positions"
    error_message = "the old stack keeps the management bucket"
  }

  assert {
    condition = jsonencode(var.datasets[0].readers) == jsonencode([
      "arn:aws:iam::650503560686:role/jwall-engineering-braveheart-trainer-task-gpu",
      "arn:aws:iam::570327089884:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_013589f39f92382a",
      "arn:aws:iam::650503560686:role/jwall-engineering-ds-braveheart-selfplay-positions",
    ])
    error_message = "the readers are today's, plus production's admin role for the copy, and nothing else"
  }

  assert {
    condition     = var.datasets[0].versioning && var.datasets[0].expire_noncurrent_days == null && length(var.datasets[0].expire_prefixes) == 0
    error_message = "the old bucket keeps its retention: versioned, nothing expires"
  }
}
