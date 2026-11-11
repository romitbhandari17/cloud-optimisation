## Cloudineer Central Platform — root composition
#
# Deployed once in CLOUDINEER's own AWS account. Wires together the reusable
# modules/ building blocks: storage (s3, dynamodb) + compute (agents, sfn).
#
# Per-customer resources (the cross-account read-only IAM role) are NOT applied
# here — they're deployed into each customer's own AWS account via
# terraform/customer-onboarding, which reuses modules/customer-role.
#
# Usage:
#   ../scripts/build_lambda_artifacts.sh
#   terraform init
#   terraform apply

module "reports_bucket" {
  source = "./modules/s3"

  project_name = var.project_name
  tags         = var.tags
}

module "customer_registry" {
  source = "./modules/dynamodb"

  project_name = var.project_name
  tags         = var.tags
}

module "agents" {
  source = "./modules/agents"

  project_name           = var.project_name
  function_zip_path      = var.function_zip_path
  layer_zip_path         = var.layer_zip_path
  reports_bucket_name    = module.reports_bucket.bucket_name
  reports_bucket_arn     = module.reports_bucket.bucket_arn
  lambda_timeout_seconds = var.lambda_timeout_seconds
  lambda_memory_mb       = var.lambda_memory_mb
  log_retention_days     = var.log_retention_days
  tags                   = var.tags
}

module "sfn" {
  source = "./modules/sfn"

  project_name                = var.project_name
  discovery_lambda_arn        = module.agents.agent_lambda_arns["discovery"]
  cost_analysis_lambda_arn    = module.agents.agent_lambda_arns["cost-analysis"]
  compute_optimisation_lambda_arn = module.agents.agent_lambda_arns["compute-optimisation"]
  db_optimisation_lambda_arn  = module.agents.agent_lambda_arns["db-optimisation"]
  dashboard_lambda_arn        = module.agents.dashboard_lambda_arn
  tags                        = var.tags
}

module "api" {
  source = "./modules/api"

  project_name        = var.project_name
  function_zip_path   = var.function_zip_path
  layer_arn           = module.agents.dependencies_layer_arn
  reports_bucket_name = module.reports_bucket.bucket_name
  reports_bucket_arn  = module.reports_bucket.bucket_arn
  state_machine_arn   = module.sfn.state_machine_arn
  tags                = var.tags
}
