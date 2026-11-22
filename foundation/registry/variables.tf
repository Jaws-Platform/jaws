variable "directory" {
  description = "The registry directory, datasets/ at the repository root: one <owner>/<name>.yaml per onboarded dataset, and README.md."
  type        = string
}

variable "name_root" {
  description = "The root of every name (config/tool.yaml `context.name_root`), for example `jaws`."
  type        = string
}

variable "live_location_names" {
  description = "Every external location the shared host lists (the `names` of `databricks_external_locations`). The provider reports none as null, which is accepted."
  type        = list(string)
  default     = null
  nullable    = true
}

variable "live_location_urls" {
  description = "The URL of each live location in `live_names_to_check`, by name, as Databricks stores it (with or without a trailing slash)."
  type        = map(string)
  default     = {}
}

variable "reserved_catalogs" {
  description = "Catalog names already taken by Databricks workspace projects (each workspace's own catalog, `<project>` with `-` replaced by `_`): no producer catalog may take one."
  type        = list(string)
  default     = []
}
