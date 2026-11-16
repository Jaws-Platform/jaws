# The onboarded datasets, derived from datasets/<owner>/<name>.yaml exactly as
# access.py's load_registry derives them (tests/fixtures/datasets-expected.json
# is both implementations' expected output). Pure: no resources, no providers.
#
# Two registry datasets can never overlap each other: each id has its own bucket
# (<organization>-<owner>-<name>), so two URLs could meet only through two ids
# sharing a key, which is refused below. Overlap with locations already in the
# metastore is the foundation's live check (databricks.tf).

locals {
  # The README is the one file that is not a dataset.
  files = sort([for f in fileset(var.directory, "**") : f if f != "README.md"])

  # <owner>/<name>.yaml, both kebab-case: anything else is misplaced.
  well_placed = [for f in local.files : f if can(regex("^[a-z0-9]+(-[a-z0-9]+)*/[a-z0-9]+(-[a-z0-9]+)*\\.yaml$", f))]
  misplaced   = setsubtract(local.files, local.well_placed)

  raw = { for f in local.well_placed : f => try(yamldecode(file("${var.directory}/${f}")), null) }

  # Exactly description (a non-empty string) and prefix (path segments ending in
  # `/`, no leading `/`).
  malformed = sort([
    for f, r in local.raw : f if !(
      can(keys(r))
      && try(toset(keys(r)) == toset(["description", "prefix"]), false)
      && try(length(trimspace(r.description)) > 0, false)
      && can(regex("^([A-Za-z0-9!_.'()-]+/)+$", r.prefix))
    )
  ])
  valid = [for f in local.well_placed : f if !contains(local.malformed, f)]

  ids  = { for f in local.valid : f => trimsuffix(f, ".yaml") }
  keys = { for f in local.valid : f => replace(local.ids[f], "/", "-") }

  too_long = sort([for f in local.valid : local.ids[f] if length(local.keys[f]) > 40])

  # Grouped, so two ids sharing a key are listed rather than failing the expression.
  by_key   = { for f in local.valid : local.keys[f] => local.ids[f]... }
  clashing = sort([for key, ids in local.by_key : "${key}: ${join(", ", sort(ids))}" if length(ids) > 1])

  # length(), not `== []`: a list never equals an empty tuple with `==`.
  datasets = length(local.clashing) == 0 ? {
    for f in local.valid : local.keys[f] => {
      id            = local.ids[f]
      owner         = split("/", local.ids[f])[0]
      name          = split("/", local.ids[f])[1]
      prefix        = local.raw[f].prefix
      description   = local.raw[f].description
      platform_name = "${var.organization}-ds-${local.keys[f]}"
      bucket        = "${var.organization}-${local.keys[f]}"
      url           = "s3://${var.organization}-${local.keys[f]}/${trimsuffix(local.raw[f].prefix, "/")}"
      # In Unity Catalog: the producer's catalog, the dataset's schema in it,
      # and its external volume (/Volumes/<catalog>/<schema>/files/).
      catalog = replace(split("/", local.ids[f])[0], "-", "_")
      schema  = replace(split("/", local.ids[f])[1], "-", "_")
      volume  = "files"
    }
  } : {}
}

# The live overlap check's two halves (the foundation reads the locations):
# which live locations to read, and which of them overlap a dataset. Unity
# Catalog refuses an external location equal to, inside or containing another.
locals {
  onboarded_names = toset([for d in values(local.datasets) : d.platform_name])

  # The provider reports an empty list as null.
  live_names          = var.live_location_names == null ? toset([]) : toset(var.live_location_names)
  live_names_to_check = setsubtract(local.live_names, local.onboarded_names)

  # Compared with a trailing slash, so s3://b/data and s3://b/data2 are not nested.
  live_urls = { for name, url in var.live_location_urls : name => trimsuffix(url, "/") }
  overlaps = sort(flatten([
    for key, d in local.datasets : [
      for name, url in local.live_urls : "${d.id} (${d.url}) and ${name} (${url})"
      if startswith("${d.url}/", "${url}/") || startswith("${url}/", "${d.url}/")
    ]
  ]))
}

# A producer catalog may not take a Databricks workspace project's own catalog
# name (each workspace's catalog is <project> with - replaced by _).
locals {
  catalog_clashes = sort(distinct([
    for f in local.valid : replace(split("/", local.ids[f])[0], "-", "_")
    if contains(var.reserved_catalogs, replace(split("/", local.ids[f])[0], "-", "_"))
  ]))
}
