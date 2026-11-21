# The braveheart sample with running hours (render.py): 08:00-20:00 UTC on weekdays.
mock_provider "aws" {
  source = "./tests/mocks"
}

run "plans_the_start_drain_and_stop_schedules" {
  command = plan

  assert {
    condition     = var.schedule == { days = "weekdays", start = "08:00", stop = "20:00" }
    error_message = "the project file's schedule reaches the stack"
  }

  assert {
    condition = module.bot[0].schedule == {
      start = { name = "jaws-braveheart-bot-start", expression = "cron(0 8 ? * MON-FRI *)" }
      drain = { name = "jaws-braveheart-bot-drain", expression = "cron(0 20 ? * MON-FRI *)" }
      stop  = { name = "jaws-braveheart-bot-stop", expression = "cron(0 21 ? * MON-FRI *)" }
    }
    error_message = "the module plans the three schedules, Monday to Friday, with the hard stop an hour after the drain"
  }
}
