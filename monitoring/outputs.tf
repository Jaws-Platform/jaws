# Conditionals rather than try(): try() of a partly unknown value is wholly unknown at plan.

output "node" {
  description = "The monitoring node: its instance, address, role, config bucket, parameters, data volume, Grafana URL and watchdog. Null without the monitoring section."
  value       = local.enabled ? module.monitoring[0].node : null
}

output "normalizer" {
  description = "The billing normalizer: its function, role, log group, schedule and where it writes. Null without the monitoring section."
  value       = local.enabled ? module.monitoring[0].normalizer : null
}

output "vpc_id" {
  description = "The stack's own VPC. Null without the monitoring section."
  value       = local.enabled ? module.network[0].vpc_id : null
}
