output "repository_uri" {
  description = "The image's public address, public.ecr.aws/<alias>/jaws: the repository variable JAWS_PUBLIC_IMAGE."
  value       = aws_ecrpublic_repository.jaws.repository_uri
}

output "role_arn" {
  description = "The publishing role's ARN: the repository variable JAWS_PUBLISH_ROLE_ARN."
  value       = module.publish_role.arn
}
