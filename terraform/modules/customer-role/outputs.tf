output "role_arn" {
  description = "ARN to put into this customer's config/customers/<id>.yaml `role_arn` field."
  value       = aws_iam_role.assessment.arn
}

output "role_name" {
  value = aws_iam_role.assessment.name
}
