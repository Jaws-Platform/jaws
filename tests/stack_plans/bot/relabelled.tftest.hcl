# The braveheart sample on a platform with its own ManagedBy: the stack accepts
# the value the CLI stamps, and only that value.
mock_provider "aws" {
  source = "./tests/mocks"
}

run "accepts_the_platform_s_managed_by" {
  command = plan

  assert {
    condition     = var.managed_by == "ACME" && var.tags["ManagedBy"] == "ACME"
    error_message = "ManagedBy is the platform's context.managed_by, and the stack checks the tag against it"
  }
}

run "refuses_a_managed_by_the_platform_did_not_stamp" {
  command = plan

  variables {
    managed_by = "JAWS"
  }

  expect_failures = [var.tags]
}
