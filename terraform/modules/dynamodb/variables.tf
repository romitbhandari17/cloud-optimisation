variable "project_name" {
  description = "Prefix used for the customer registry table name."
  type        = string
  default     = "cloudineer-finops"
}

variable "tags" {
  type    = map(string)
  default = {}
}
