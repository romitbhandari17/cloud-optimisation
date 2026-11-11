variable "aws_region" {
  description = "AWS region Cloudineer's central platform is deployed in."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix used for all central-platform resource names."
  type        = string
  default     = "cloudineer-finops"
}

variable "function_zip_path" {
  description = "Path to dist/cloudineer_function.zip (run scripts/build_lambda_artifacts.sh first)."
  type        = string
  default     = "../dist/cloudineer_function.zip"
}

variable "layer_zip_path" {
  description = "Path to dist/cloudineer_layer.zip (run scripts/build_lambda_artifacts.sh first)."
  type        = string
  default     = "../dist/cloudineer_layer.zip"
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
