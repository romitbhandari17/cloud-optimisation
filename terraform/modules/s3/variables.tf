variable "project_name" {
  description = "Prefix used for the reports bucket name."
  type        = string
  default     = "cloudineer-finops"
}

variable "tags" {
  type    = map(string)
  default = {}
}
