variable "project_name" {
  description = "Prefix used for all Lambda/IAM/API Gateway resource names."
  type        = string
  default     = "cloudineer-finops"
}

variable "function_zip_path" {
  description = "Path to dist/cloudineer_function.zip (run scripts/build_lambda_artifacts.sh first)."
  type        = string
}

variable "layer_arn" {
  description = "ARN of the shared dependency layer (modules/agents output)."
  type        = string
}

variable "reports_bucket_name" {
  type = string
}

variable "reports_bucket_arn" {
  type = string
}

variable "state_machine_arn" {
  type = string
}

variable "lambda_timeout_seconds" {
  type    = number
  default = 30
}

variable "lambda_memory_mb" {
  type    = number
  default = 256
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "tags" {
  type    = map(string)
  default = {}
}
