variable "config_path" {
  description = "The tool configuration: a directory of .yaml files, or one .yaml file holding every section. Null reads config/ at the repository root, as the foundation does."
  type        = string
  default     = null
}
