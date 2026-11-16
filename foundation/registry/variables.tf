variable "directory" {
  description = "The registry directory, datasets/ at the repository root: one <owner>/<name>.yaml per onboarded dataset, and README.md."
  type        = string
}

variable "organization" {
  description = "The organization prefix of every name, for example `jwall-engineering`."
  type        = string
}
