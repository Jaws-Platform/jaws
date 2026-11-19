# braveheart-selfplay's production stack once braveheart-trainer has one there
# too: the positions bucket now names the trainer's production GPU role as its
# reader. Applied after the trainer's first production apply has created that
# role (a bucket policy cannot name a role that does not exist).
mock_provider "aws" {
  source = "./tests/mocks"
}

run "the_positions_admit_the_trainer_in_production" {
  command = plan

  assert {
    condition     = var.datasets[0].bucket == "jaws-braveheart-selfplay-positions"
    error_message = "the production stack keeps production's bucket"
  }

  assert {
    condition     = jsonencode(var.datasets[0].readers) == jsonencode(["arn:aws:iam::570327089884:role/jaws-braveheart-trainer-task-gpu"])
    error_message = "the trainer's production GPU role, and only it, reads the positions: no management role, no admin, and no Databricks share role while Databricks is off there"
  }
}
