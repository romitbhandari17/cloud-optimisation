output "state_machine_arn" {
  value = module.sfn.state_machine_arn
}

output "lambda_execution_role_arn" {
  description = "Use as the `trusted_principal_arns` input to terraform/customer-onboarding."
  value       = module.agents.lambda_execution_role_arn
}

output "reports_bucket_name" {
  value = module.reports_bucket.bucket_name
}

output "customer_registry_table_name" {
  value = module.customer_registry.table_name
}

output "api_base_url" {
  description = "Put this in ui/config.js as API_BASE_URL to connect the dashboard UI."
  value       = module.api.api_base_url
}
