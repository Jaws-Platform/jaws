output "arn" {
  description = "The export's ARN. Null without monitoring.cost.aws."
  value       = local.enabled ? module.export[0].arn : null
}

output "name" {
  description = "The export's name, <name_root>-focus-daily. Null without monitoring.cost.aws."
  value       = local.enabled ? module.export[0].name : null
}

output "delivery_prefix" {
  description = "Where AWS delivers in the billing bucket, and where the monitoring stack's normalizer reads. Null without monitoring.cost.aws."
  value       = local.enabled ? module.export[0].delivery_prefix : null
}
