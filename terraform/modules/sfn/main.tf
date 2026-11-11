## Assessment Step Functions state machine
#
# Fans out to the three agent Lambdas in parallel (with per-branch Catch fallbacks),
# then invokes the dashboard Lambda to aggregate results (docs/architecture.md §5).
# Adding agent #4 means adding a branch to statemachine/assessment.asl.json and a
# new `*_lambda_arn` variable/templatefile binding here.

data "aws_iam_policy_document" "sfn_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "state_machine" {
  name               = "${var.project_name}-assessment-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.sfn_trust.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "state_machine_invoke_lambda" {
  name = "${var.project_name}-sfn-invoke-lambda"
  role = aws_iam_role.state_machine.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "InvokeAgentLambdas"
      Effect = "Allow"
      Action = ["lambda:InvokeFunction"]
      Resource = [
        var.discovery_lambda_arn,
        var.cost_analysis_lambda_arn,
        var.compute_optimisation_lambda_arn,
        var.db_optimisation_lambda_arn,
        var.network_optimisation_lambda_arn,
        var.dashboard_lambda_arn,
      ]
    }]
  })
}

resource "aws_sfn_state_machine" "assessment" {
  name     = "${var.project_name}-assessment"
  role_arn = aws_iam_role.state_machine.arn
  tags     = var.tags

  definition = templatefile("${path.module}/statemachine/assessment.asl.json", {
    discovery_lambda_arn            = var.discovery_lambda_arn
    cost_analysis_lambda_arn        = var.cost_analysis_lambda_arn
    compute_optimisation_lambda_arn = var.compute_optimisation_lambda_arn
    db_optimisation_lambda_arn      = var.db_optimisation_lambda_arn
    network_optimisation_lambda_arn = var.network_optimisation_lambda_arn
    dashboard_lambda_arn            = var.dashboard_lambda_arn
  })
}
