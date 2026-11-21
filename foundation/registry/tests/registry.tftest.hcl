# The registry module derives each onboarded dataset from datasets/<owner>/<name>.yaml,
# as access.py's load_registry does. Both must give tests/fixtures/datasets-expected.json
# for tests/fixtures/datasets (tests/test_access_registry.py checks the Python half):
# two implementations, one expected output, no source-text matching.

variables {
  organization = "jaws"
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

# The live overlap check (foundation/databricks.tf): the module is given what
# the shared host lists, and says which locations to read and which overlap.

run "a_host_that_lists_no_location_leaves_nothing_to_check" {
  command = plan

  variables {
    directory           = "../../tests/fixtures/datasets"
    live_location_names = null # how the provider reports an empty list
  }

  assert {
    condition     = length(output.live_names_to_check) == 0 && length(output.overlaps) == 0
    error_message = "a host that lists no location (null) leaves nothing to read and nothing overlapping"
  }
}

run "every_live_location_but_the_onboarded_ones_is_checked" {
  command = plan

  variables {
    directory           = "../../tests/fixtures/datasets"
    live_location_names = ["jaws-ds-braveheart-selfplay-positions", "braveheart-databricks-catalog"]
  }

  assert {
    condition     = jsonencode(output.live_names_to_check) == jsonencode(["braveheart-databricks-catalog"])
    error_message = "an onboarded dataset's own location is not checked against itself"
  }
}

run "a_live_location_equal_to_inside_or_containing_a_dataset_overlaps" {
  command = plan

  variables {
    directory = "../../tests/fixtures/datasets"
    live_location_urls = {
      old-share = "s3://jaws-braveheart-selfplay-positions/data/"
      root      = "s3://jaws-braveheart-selfplay-positions"
      inside    = "s3://jaws-braveheart-selfplay-positions/data/selfplay"
      sibling   = "s3://jaws-braveheart-selfplay-positions/data2"
      other     = "s3://jaws-braveheart-selfplay-positions-2/data"
    }
  }

  assert {
    condition = jsonencode(output.overlaps) == jsonencode([
      "braveheart-selfplay/positions (s3://jaws-braveheart-selfplay-positions/data) and inside (s3://jaws-braveheart-selfplay-positions/data/selfplay)",
      "braveheart-selfplay/positions (s3://jaws-braveheart-selfplay-positions/data) and old-share (s3://jaws-braveheart-selfplay-positions/data)",
      "braveheart-selfplay/positions (s3://jaws-braveheart-selfplay-positions/data) and root (s3://jaws-braveheart-selfplay-positions)",
    ])
    error_message = "equal, containing and contained locations overlap; a sibling prefix and another bucket do not"
  }
}

run "a_catalog_named_like_a_workspace_catalog_is_refused" {
  command = plan

  variables {
    directory         = "../../tests/fixtures/datasets"
    reserved_catalogs = ["braveheart_selfplay"]
  }

  expect_failures = [output.datasets]
}
