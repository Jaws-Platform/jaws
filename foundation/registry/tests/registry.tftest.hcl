# The registry module derives each onboarded dataset from datasets/<owner>/<name>.yaml,
# as access.py's load_registry does. Both must give tests/fixtures/datasets-expected.json
# for tests/fixtures/datasets (tests/test_access_registry.py checks the Python half):
# two implementations, one expected output, no source-text matching.

variables {
  organization = "jwall-engineering"
}

run "derives_what_python_derives" {
  command = plan

  variables {
    directory = "../../tests/fixtures/datasets"
  }

  assert {
    condition     = jsonencode(output.datasets) == jsonencode(jsondecode(file("../../tests/fixtures/datasets-expected.json")))
    error_message = "the registry module derives tests/fixtures/datasets-expected.json, as load_registry does"
  }
}

run "an_empty_registry_is_empty" {
  command = plan

  variables {
    directory = "tests/fixtures/empty"
  }

  assert {
    condition     = length(output.datasets) == 0
    error_message = "a directory holding only the README onboards nothing"
  }
}

run "a_key_over_40_characters_is_refused" {
  command = plan

  variables {
    directory = "tests/fixtures/long"
  }

  expect_failures = [output.datasets]
}

run "two_ids_with_one_key_are_refused" {
  command = plan

  variables {
    directory = "tests/fixtures/clash"
  }

  expect_failures = [output.datasets]
}

run "a_misplaced_file_is_refused" {
  command = plan

  variables {
    directory = "tests/fixtures/misplaced"
  }

  expect_failures = [output.datasets]
}

run "a_file_without_exactly_description_and_prefix_is_refused" {
  command = plan

  variables {
    directory = "tests/fixtures/extra-key"
  }

  expect_failures = [output.datasets]
}
