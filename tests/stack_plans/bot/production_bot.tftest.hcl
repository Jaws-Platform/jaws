# braveheart-bot's live file rendered in the production view, as while it moves:
# the file states Organization jwall-engineering, the CLI stamps production's
# tags over it, and the stack names everything from the stamped tag.
mock_provider "aws" {
  source = "./tests/mocks"
}

run "plans_the_bot_under_production_s_names" {
  command = plan

  assert {
    condition     = var.tags["Organization"] == "jaws" && var.tags["ManagedBy"] == "jaws"
    error_message = "production's Organization and ManagedBy are stamped over the file's"
  }

  assert {
    condition     = local.name == "jaws-braveheart-bot"
    error_message = "every name in production starts with jaws-, never the file's organization"
  }

  assert {
    condition     = var.bot_enabled && length(module.image) == 1 && length(module.bot) == 1 && length(module.records) == 1
    error_message = "the moving bot has its image repository, instance and records bucket in production"
  }
}
