variable "cloudineer_account_id" {
  description = "Cloudineer's central AWS account ID that will assume this role."
  type        = string
}

variable "trusted_principal_arns" {
  description = <<-EOT
    Specific IAM principal ARN(s) in Cloudineer's account allowed to assume this role
    (recommended: the `lambda_execution_role_arn` output of terraform/compute, for
    least privilege). Defaults to the whole account's root principal, which is
    simplest for early onboarding/testing but broader than necessary in production.
  EOT
  type        = list(string)
  default     = []
}

variable "external_id" {
  description = <<-EOT
    Unique external ID for this customer (see docs/context2.txt §2 step 1). Must match
    the value stored in this customer's config/customers/<id>.yaml `external_id` field.
    Prevents the "confused deputy" problem for cross-account assume-role.
  EOT
  type        = string
}

variable "role_name" {
  description = "Name of the read-only role Cloudineer assumes for assessments."
  type        = string
  default     = "CloudineerFinOpsReadOnlyRole"
}

variable "max_session_duration_seconds" {
  description = "Maximum STS session duration for this role."
  type        = number
  default     = 3600
}

variable "tags" {
  description = "Tags applied to all resources created by this module."
  type        = map(string)
  default     = {}
}
