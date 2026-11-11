from unittest.mock import patch

import boto3

from cloudineer.agents.cost_analysis_agent import CostAnalysisAgent
from cloudineer.core.ai.bedrock_client import AIFallback
from cloudineer.core.context import AgentContext
from cloudineer.core.contract import AssessmentRequest
from cloudineer.core.tools.base import ToolRegistry


def test_cost_analysis_falls_back_to_generic_recommendation_when_ai_disabled():
    ctx = AgentContext(
        request=AssessmentRequest(customer_id="c1", account_id="123456789012"),
        session=boto3.Session(region_name="us-east-1"),
        tools=ToolRegistry(),
        ai=AIFallback(enabled=False),
    )

    with patch.object(
        CostAnalysisAgent,
        "_get_cost_by_service",
        return_value={"Amazon EC2": 800.0, "Amazon S3": 50.0},
    ):
        result = CostAnalysisAgent().safe_run(ctx)

    assert not result.errors
    assert len(result.findings) == 1  # only EC2 clears the 10% significant-share bar
    finding = result.findings[0]
    assert finding.resource_id == "Amazon EC2"
    assert finding.estimated_monthly_savings == 0.0
    assert finding.ai_explanation  # generic fallback recommendation is always present
