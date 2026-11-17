locals {
  access_portal_url = "https://${one(data.aws_ssoadmin_instances.this.identity_store_ids)}.awsapps.com/start"
}

output "access_portal_url" {
  description = "The AWS access portal: sign in here for the console, and the sso_start_url of the CLI profile."
  value       = local.access_portal_url
}

output "admin_role_arn" {
  description = "The IAM role Identity Center provisioned for AdministratorAccess. Copy it into bucket_admin_principal_arns in foundation/state.tf. Null until IAM lists the role: run `terraform apply -refresh-only`."
  value       = module.owner_admin.role_arn
}

output "permission_set_arn" {
  description = "ARN of the AdministratorAccess permission set."
  value       = module.owner_admin.permission_set_arn
}

output "aws_config" {
  description = "The ~/.aws/config blocks for the jwall-admin profile (the management account) and the jaws-prod profile (production): terraform output -raw aws_config."
  value       = <<-EOT
    [sso-session jwall-engineering]
    sso_start_url = ${local.access_portal_url}
    sso_region = ${local.region}
    sso_registration_scopes = sso:account:access

    [profile jwall-admin]
    sso_session = jwall-engineering
    sso_account_id = ${local.account_id}
    sso_role_name = ${module.owner_admin.permission_set_name}
    region = ${local.region}

    [profile jaws-prod]
    sso_session = jwall-engineering
    sso_account_id = ${local.production_account_id}
    sso_role_name = ${module.owner_admin.permission_set_name}
    region = ${local.region}
  EOT
}
