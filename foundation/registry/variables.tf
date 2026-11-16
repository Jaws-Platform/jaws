variable "directory" {
  description = "The registry directory, datasets/ at the repository root: one <owner>/<name>.yaml per onboarded dataset, and README.md."
  type        = string
}

variable "organization" {
  description = "The organization prefix of every name, for example `jwall-engineering`."
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
