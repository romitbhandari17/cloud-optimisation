## Customer onboarding — applied in the CUSTOMER's AWS account
#
# Thin wrapper around modules/customer-role so onboarding a new customer is a
# single `terraform apply` with customer-specific variables, while the actual
# IAM role definition stays a single reusable module.

module "customer_role" {
  source = "../modules/customer-role"

  cloudineer_account_id        = var.cloudineer_account_id
  trusted_principal_arns       = var.trusted_principal_arns
  external_id                  = var.external_id
  role_name                    = var.role_name
  max_session_duration_seconds = var.max_session_duration_seconds
  tags                         = var.tags
}
