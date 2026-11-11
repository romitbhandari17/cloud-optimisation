## Agent Lambdas
#
# One Lambda per Cloudineer agent + one Lambda that aggregates their results into
# the Assessment Dashboard (docs/architecture.md §5). Adding a new agent (e.g. a
# future RDS/database agent) means adding one entry to `local.agent_functions` and
# a new handler under src/cloudineer/handlers/ — nothing else in this module
# changes. The Step Functions wiring lives in ../sfn.

data "aws_caller_identity" "current" {}

resource "aws_lambda_layer_version" "dependencies" {
  layer_name          = "${var.project_name}-deps"
  filename            = var.layer_zip_path
  source_code_hash    = filebase64sha256(var.layer_zip_path)
  compatible_runtimes = ["python3.12"]
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "agent_lambda" {
  name               = "${var.project_name}-agent-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = var.tags
}

data "aws_iam_policy_document" "agent_lambda_permissions" {
  statement {
    sid       = "Logging"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:*:${data.aws_caller_identity.current.account_id}:*"]
  }

  statement {
    sid    = "AssumeCustomerAssessmentRoles"
    effect = "Allow"
    # Customer roles grant trust to this role's ARN specifically (see
    # modules/customer-role's `trusted_principal_arns`), so "*" here is scoped in
    # practice by the customer-side trust policy + externalId, not by this statement.
    actions   = ["sts:AssumeRole"]
    resources = ["*"]
  }

  statement {
    sid    = "BedrockAIFallback"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:Converse",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "agent_lambda_permissions" {
  name   = "${var.project_name}-agent-lambda-permissions"
  role   = aws_iam_role.agent_lambda.id
  policy = data.aws_iam_policy_document.agent_lambda_permissions.json
}

resource "aws_iam_role_policy" "dashboard_lambda_s3" {
  name = "${var.project_name}-dashboard-lambda-s3"
  role = aws_iam_role.agent_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "WriteReports"
      Effect   = "Allow"
      Action   = ["s3:PutObject"]
      Resource = "${var.reports_bucket_arn}/*"
    }]
  })
}

locals {
  agent_functions = {
    discovery            = "cloudineer.handlers.discovery_handler.handler"
    cost-analysis        = "cloudineer.handlers.cost_analysis_handler.handler"
    compute-optimisation = "cloudineer.handlers.compute_optimisation_handler.handler"
    db-optimisation      = "cloudineer.handlers.db_optimisation_handler.handler"
  }
}

resource "aws_cloudwatch_log_group" "agent" {
  for_each          = local.agent_functions
  name              = "/aws/lambda/${var.project_name}-${each.key}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_lambda_function" "agent" {
  for_each         = local.agent_functions
  function_name    = "${var.project_name}-${each.key}"
  role             = aws_iam_role.agent_lambda.arn
  handler          = each.value
  runtime          = "python3.12"
  timeout          = var.lambda_timeout_seconds
  memory_size      = var.lambda_memory_mb
  filename         = var.function_zip_path
  source_code_hash = filebase64sha256(var.function_zip_path)
  layers           = [aws_lambda_layer_version.dependencies.arn]
  tags             = var.tags

  depends_on = [aws_cloudwatch_log_group.agent]
}

resource "aws_cloudwatch_log_group" "dashboard" {
  name              = "/aws/lambda/${var.project_name}-dashboard"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_lambda_function" "dashboard" {
  function_name    = "${var.project_name}-dashboard"
  role             = aws_iam_role.agent_lambda.arn
  handler          = "cloudineer.handlers.dashboard_handler.handler"
  runtime          = "python3.12"
  timeout          = var.lambda_timeout_seconds
  memory_size      = var.lambda_memory_mb
  filename         = var.function_zip_path
  source_code_hash = filebase64sha256(var.function_zip_path)
  layers           = [aws_lambda_layer_version.dependencies.arn]
  tags             = var.tags

  environment {
    variables = {
      CLOUDINEER_REPORTS_BUCKET = var.reports_bucket_name
    }
  }

  depends_on = [aws_cloudwatch_log_group.dashboard]
}
