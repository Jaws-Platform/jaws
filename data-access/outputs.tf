output "fingerprint" {
  description = "The fingerprint of the variables this state was applied with: the scheduled sweep skips a run whose render has the same one and leaves nothing waiting."
  value       = var.fingerprint
}

output "edges" {
  description = "Each dataset's bound consumers, by key, sorted."
  value       = { for key, m in module.access : key => m.consumers }
}

output "awaiting_onboarding" {
  description = "Keys of datasets whose external location does not exist yet: the foundation release that onboards them has not applied."
  value       = local.awaiting_onboarding
}

output "missing_workspaces" {
  description = "Consumers with no <project>-prod workspace yet, by dataset key: bound by the first sweep after their Databricks apply."
  value       = local.missing_workspaces
}
