## Cloudineer cross-account Assessment Role
#
# Deployed in the CUSTOMER's AWS account. Grants Cloudineer's central account
# read-only access to run the Discovery, Cost Analysis and EC2 Optimisation agents,
# per docs/architecture.md §3 ("Two permission profiles") and docs/context2.txt §2.
#
# No write/modify/delete permissions are granted. A separate, explicitly-approved
# "Remediation Role" module is a future addition — never widen this role instead.

locals {
  # Falls back to the account root principal (simplest for onboarding/testing) unless
  # specific principal ARNs (e.g. the central Lambda execution role) are supplied.
  trust_principals = length(var.trusted_principal_arns) > 0 ? var.trusted_principal_arns : [
    "arn:aws:iam::${var.cloudineer_account_id}:root"
  ]
}

data "aws_iam_policy_document" "trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = local.trust_principals
    }

    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [var.external_id]
    }
  }
}

data "aws_iam_policy_document" "assessment_read_only" {
  statement {
    sid    = "DiscoveryAndInventory"
    effect = "Allow"
    actions = [
      "ec2:Describe*",
      "rds:Describe*",
      "rds:ListTagsForResource",
      "s3:ListAllMyBuckets",
      "s3:GetBucketLocation",
      "s3:GetBucketTagging",
      "s3:GetLifecycleConfiguration",
      "lambda:ListFunctions",
      "lambda:GetFunction",
      "ecs:ListClusters",
      "ecs:DescribeClusters",
      "ecs:ListServices",
      "ecs:DescribeServices",
      "eks:ListClusters",
      "eks:DescribeCluster",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "CostAndUsage"
    effect = "Allow"
    actions = [
      "ce:GetCostAndUsage",
      "ce:GetCostForecast",
      "ce:GetAnomalies",
      "ce:GetAnomalyMonitors",
      "ce:GetDimensionValues",
      "ce:GetTags",
      "budgets:ViewBudget",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "MetricsAndRecommendations"
    effect = "Allow"
    actions = [
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:GetMetricData",
      "cloudwatch:ListMetrics",
      "compute-optimizer:GetEC2InstanceRecommendations",
      "compute-optimizer:GetEnrollmentStatus",
      "support:DescribeTrustedAdvisorChecks",
      "support:DescribeTrustedAdvisorCheckResult",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "CallerIdentity"
    effect    = "Allow"
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "assessment_read_only" {
  name        = "${var.role_name}Policy"
  description = "Cloudineer FinOps assessment read-only permissions"
  policy      = data.aws_iam_policy_document.assessment_read_only.json
  tags        = var.tags
}

resource "aws_iam_role" "assessment" {
  name                 = var.role_name
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = var.max_session_duration_seconds
  description          = "Read-only role assumed by Cloudineer's central platform to run cost assessments"
  tags                 = var.tags
}

resource "aws_iam_role_policy_attachment" "assessment_read_only" {
  role       = aws_iam_role.assessment.name
  policy_arn = aws_iam_policy.assessment_read_only.arn
}
