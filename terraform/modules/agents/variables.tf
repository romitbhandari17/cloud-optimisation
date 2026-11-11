variable "project_name" {
  description = "Prefix used for all Lambda/IAM resource names."
  type        = string
  default     = "cloudineer-finops"
}

variable "function_zip_path" {
  description = "Path to dist/cloudineer_function.zip (run scripts/build_lambda_artifacts.sh first)."
  type        = string
}

variable "layer_zip_path" {
  description = "Path to dist/cloudineer_layer.zip (run scripts/build_lambda_artifacts.sh first)."
  type        = string
}

variable "reports_bucket_name" {
  description = "Central reports S3 bucket name (modules/s3 output) the dashboard Lambda writes to."
  type        = string
}

variable "reports_bucket_arn" {
  description = "Central reports S3 bucket ARN (modules/s3 output), used to scope the write IAM policy."
  type        = string
}

variable "lambda_timeout_seconds" {
  type    = number
  default = 120
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
