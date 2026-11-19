# braveheart-trainer's live file in the management view while it and
# braveheart-selfplay move: its old stack, unchanged except that the nets bucket
# lets production's admin role read it, for the owner's server-side copy.
mock_provider "aws" {
  source = "./tests/mocks"
}

run "the_old_nets_bucket_admits_the_copy" {
  command = plan

  assert {
    condition     = toset(keys(module.datasets)) == toset(["nets"]) && var.datasets[0].bucket == "jwall-engineering-braveheart-trainer-nets"
    error_message = "the old stack keeps the management bucket"
  }

  assert {
    condition = jsonencode(var.datasets[0].readers) == jsonencode([
      "arn:aws:iam::650503560686:role/jwall-engineering-braveheart-selfplay-task-relabel",
      "arn:aws:iam::570327089884:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_013589f39f92382a",
    ])
    error_message = "the readers are self-play's management relabel role (its old stack still exists) and production's admin role for the copy, and nothing else"
  }

  assert {
    condition     = var.datasets[0].versioning && var.datasets[0].expire_noncurrent_days == null && length(var.datasets[0].expire_prefixes) == 0
    error_message = "the old bucket keeps its retention: versioned, nothing expires"
  }
}
