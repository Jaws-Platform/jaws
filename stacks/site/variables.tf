# The site stack jaws renders for one site. Every value
# comes from the site repository's jaws.yaml or from
# the tool configuration (config/); the CLI writes them to terraform.tfvars.json.

variable "project" {
  description = "Project name in kebab-case. The site bucket is `<name_root>-<project>`, for example `jaws-<project>`."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]+(-[a-z0-9]+)*$", var.project)) && length(var.project) <= 30
    error_message = "project must be kebab-case and at most 30 characters."
  }
}

variable "name_root" {
  description = "The root of every name in this stack (`<name_root>-<project>...`): config/tool.yaml `context.name_root`, for example `jaws`. A name only; the `Organization` tag is the project's GitHub owner."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]+(-[a-z0-9]+)*$", var.name_root))
    error_message = "name_root must be kebab-case: lowercase letters, digits and single hyphens."
  }
}

variable "managed_by" {
  description = "The ManagedBy tag the platform stamps on everything (config/tool.yaml `context.managed_by`, `JAWS` unless the platform sets another). tags.ManagedBy must equal it."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9]+(-[A-Za-z0-9]+)*$", var.managed_by))
    error_message = "managed_by must be letters, digits and single hyphens, such as JAWS."
  }
}

variable "repository" {
  description = "GitHub repository of the site, as `owner/repo`. Must match `tags.Repository`."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9._-]+$", var.repository))
    error_message = "repository must be an `owner/repo` string."
  }
}

variable "domain_name" {
  description = "Production FQDN. Previews are served from `pr-<n>.preview.<domain_name>`."
  type        = string

  validation {
    condition     = can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.domain_name))
    error_message = "domain_name must be a lowercase FQDN without a trailing dot."
  }
}

variable "dev_domain_name" {
  description = "Optional FQDN of the dev environment, served from `<bucket>/dev`. `null` to skip it."
  type        = string
  default     = null
}

variable "enable_preview" {
  description = "Whether to create the `*.preview.<domain_name>` distribution."
  type        = bool
  default     = true
}

variable "zone_id" {
  description = "Route 53 hosted zone ID the records live in (`dns.zone_id` in config/sites.yaml)."
  type        = string

  validation {
    condition     = can(regex("^Z[A-Z0-9]{5,31}$", var.zone_id))
    error_message = "zone_id must be a Route 53 hosted zone ID."
  }
}

variable "tags" {
  description = "Tags applied to every resource through `default_tags`. The six required keys must be present; extra keys pass through."
  type        = map(string)

  validation {
    condition = alltrue([
      for key in ["Organization", "Project", "Environment", "Repository", "ManagedBy", "Owner"] :
      contains(keys(var.tags), key) && length(var.tags[key]) > 0
    ])
    error_message = "tags must contain non-empty Organization, Project, Environment, Repository, ManagedBy and Owner."
  }

  validation {
    condition     = lookup(var.tags, "Project", null) == var.project && lookup(var.tags, "Repository", null) == var.repository
    error_message = "tags.Project must equal project and tags.Repository must equal repository."
  }

  validation {
    condition     = lookup(var.tags, "ManagedBy", "") == var.managed_by && lookup(var.tags, "Environment", null) == "prod"
    error_message = "tags.ManagedBy must equal managed_by (context.managed_by, stamped by the CLI) and tags.Environment must be `prod`."
  }
}
