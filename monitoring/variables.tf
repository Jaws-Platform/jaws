variable "config_path" {
  description = "The tool configuration: a directory of .yaml files, or one .yaml file holding every section. Null reads /etc/jaws/config when the hub's image has it, else config/ at the repository root, as the foundation does; a caller passes JAWS_CONFIG (TF_VAR_config_path)."
  type        = string
  default     = null
}
