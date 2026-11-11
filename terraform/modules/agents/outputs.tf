output "agent_lambda_arns" {
  value = { for k, f in aws_lambda_function.agent : k => f.arn }
}

output "dashboard_lambda_arn" {
  value = aws_lambda_function.dashboard.arn
}

output "lambda_execution_role_arn" {
  description = "Set this as a trusted principal in each customer's modules/customer-role deployment."
  value       = aws_iam_role.agent_lambda.arn
}

output "dependencies_layer_arn" {
  value = aws_lambda_layer_version.dependencies.arn
}
