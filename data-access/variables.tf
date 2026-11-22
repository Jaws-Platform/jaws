# Every variable is rendered by `jaws access render` from
# datasets/ and every project's file, into terraform.tfvars.json. Nothing here
# is set by hand.

variable "host_workspace_url" {
  description = "The shared-objects host's URL (config/databricks.yaml databricks.shared_host_url): every onboarded dataset's location is bound and granted through it."
  type        = string

  validation {
    condition     = can(regex("^https://[a-z0-9.-]+\\.cloud\\.databricks\\.com$", var.host_workspace_url))
    error_message = "host_workspace_url must be https://<host>.cloud.databricks.com; set config/databricks.yaml databricks.shared_host_url and render again."
  }
}

variable "datasets" {
  description = "Every onboarded dataset by its key (<owner>-<name>): its id, its external location and storage credential, its producer catalog, schema and volume, and each consumer whose handshake both halves declare, with the consumer's users group and its stated purpose."
  type = map(object({
    id              = string
    location_name   = string
    credential_name = string
    catalog         = string
    schema          = string
    volume          = string
    consumers = map(object({
      users_group_name = string
      purpose          = string
    }))
  }))
  default = {}
}

variable "fingerprint" {
  description = "SHA-256 of the canonical JSON of the other variables, as `access render` computed it: traces the applied state to its render (output fingerprint)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.fingerprint))
    error_message = "fingerprint must be a lowercase SHA-256 hex digest; render the variables with `jaws access render`."
  }
}

variable "owner_group_name" {
  description = "The group that owns every onboarded dataset's objects (the metastore admin group): it is in every grant set the reconcile manages, so none is ever empty."
  type        = string

  validation {
    condition     = length(trimspace(var.owner_group_name)) > 0
    error_message = "owner_group_name must not be empty; render the variables with `jaws access render`."
  }
}
