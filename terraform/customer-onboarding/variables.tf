variable "aws_region" {
  description = "AWS region to apply this in (the IAM role itself is global, but a region is required)."
  type        = string
  default     = "us-east-1"
}

variable "cloudineer_account_id" {
  description = "Cloudineer's central AWS account ID."
  type        = string
}

variable "trusted_principal_arns" {
  description = "Recommended: [<lambda_execution_role_arn output from the root terraform/ module>]."
  type        = list(string)
  default     = []
}

variable "external_id" {
  description = "Unique per-customer external ID — must match config/customers/<id>.yaml's `external_id`."
  type        = string
}

variable "role_name" {
  type    = string
  default = "CloudineerFinOpsReadOnlyRole"
}

variable "max_session_duration_seconds" {
  type    = number
  default = 3600
}

variable "tags" {
  type    = map(string)
  default = {}
}
