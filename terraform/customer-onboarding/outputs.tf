output "role_arn" {
  description = "Put this into config/customers/<customer_id>.yaml as `role_arn`."
  value       = module.customer_role.role_arn
}

output "role_name" {
  value = module.customer_role.role_name
}
