output "fingerprint" {
  description = "The fingerprint of the variables this state was last applied with, to trace a sweep to its render. Every sweep plans regardless: nothing skips on it."
  value       = var.fingerprint
}

output "edges" {
  description = "Each dataset's bound consumers, by key, sorted."
  value       = { for key, m in module.access : key => m.consumers }
}

output "awaiting_onboarding" {
  description = "Keys of datasets whose external location, producer catalog, schema or volume does not exist yet: the foundation release that onboards them has not applied, or stopped partway."
  value       = local.awaiting_onboarding
}

output "missing_workspaces" {
  description = "Consumers with no <project>-prod workspace yet, by dataset key: bound by the first sweep after their Databricks apply."
  value       = local.missing_workspaces
}

output "catalogs" {
  description = "Each producer catalog's bound consumers, sorted: the workspaces it is bound to read-only."
  value       = { for c, m in module.catalog_access : c => m.consumers }
}
