variable "project_name" {
  description = "Prefix used for the state machine and its IAM role name."
  type        = string
  default     = "cloudineer-finops"
}

variable "discovery_lambda_arn" {
  type = string
}

variable "cost_analysis_lambda_arn" {
  type = string
}

variable "compute_optimisation_lambda_arn" {
  type = string
}

variable "db_optimisation_lambda_arn" {
  type = string
}

variable "dashboard_lambda_arn" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
