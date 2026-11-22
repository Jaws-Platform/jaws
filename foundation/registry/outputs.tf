output "datasets" {
  description = "Each onboarded dataset by its key (<owner>-<name>): id, owner, name, prefix, description, platform_name (role, credential and location), bucket and url."
  value       = local.datasets

  precondition {
    condition     = length(local.misplaced) == 0
    error_message = "datasets/ holds only <owner>/<name>.yaml (kebab-case) and README.md; misplaced: ${join(", ", sort(local.misplaced))}."
  }

  precondition {
    condition     = length(local.malformed) == 0
    error_message = "each dataset's file needs exactly description (non-empty) and prefix (path segments ending in /, no leading /); wrong: ${join(", ", local.malformed)}."
  }

  precondition {
    condition     = length(local.too_long) == 0
    error_message = "<owner>-<name> may be at most 40 characters (the consumer endpoint's key limit); too long: ${join(", ", local.too_long)}."
  }

  precondition {
    condition     = length(local.catalog_clashes) == 0
    error_message = "a producer catalog (<owner> with - replaced by _) would take a Databricks workspace project's own catalog: ${join(", ", local.catalog_clashes)}. Rename one of the projects."
  }

  precondition {
    condition     = length(local.clashing) == 0
    error_message = "two ids share a platform name (<name_root>-ds-<owner>-<name>): ${join("; ", local.clashing)}."
  }
}

output "live_names_to_check" {
  description = "The live external locations other than the onboarded datasets' own: the foundation reads each one's URL."
  value       = local.live_names_to_check
}

output "overlaps" {
  description = "Each onboarded dataset that overlaps a live location, as `<id> (<url>) and <name> (<url>)`; the foundation's plan fails on any."
  value       = local.overlaps
}
