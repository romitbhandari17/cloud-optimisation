## Customer registry table
#
# Deployed once in CLOUDINEER's own AWS account. Used as the customer/agent
# configuration + registry store referenced in docs/architecture.md §7 and
# docs/context1.txt §3 — an alternative/complement to the checked-in YAML configs
# under config/customers/.

resource "aws_dynamodb_table" "customer_registry" {
  name         = "${var.project_name}-customer-registry"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "customer_id"

  attribute {
    name = "customer_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = var.tags
}
