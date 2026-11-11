output "api_base_url" {
  description = "Base URL to put in ui/config.js as API_BASE_URL."
  value       = aws_api_gateway_stage.prod.invoke_url
}
