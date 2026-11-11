terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  # Configure credentials for the CUSTOMER's account when applying this (e.g. via
  # AWS_PROFILE, assumed role, or a dedicated onboarding credential) — this module
  # creates the role the customer is granting Cloudineer, so it must run with the
  # customer's own permissions, not Cloudineer's.
}
