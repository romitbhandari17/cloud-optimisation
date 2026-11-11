import boto3
from moto import mock_aws

from cloudineer.core.ai.bedrock_client import AIFallback
from cloudineer.core.context import AgentContext
from cloudineer.core.contract import AssessmentRequest
from cloudineer.core.tools.base import ToolRegistry
from cloudineer.agents.discovery_agent import DiscoveryAgent


@mock_aws
def test_discovery_agent_finds_ec2_instances():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro")

    ctx = AgentContext(
        request=AssessmentRequest(customer_id="c1", account_id="123456789012"),
        session=boto3.Session(region_name="us-east-1"),
        tools=ToolRegistry(),
        ai=AIFallback(enabled=False),
    )

    result = DiscoveryAgent().safe_run(ctx)

    assert result.agent == "discovery"
    assert not result.errors
    ec2_findings = [f for f in result.findings if f.resource_id.startswith("i-")]
    assert len(ec2_findings) == 1
    assert ec2_findings[0].evidence["instance_type"] == "t3.micro"


@mock_aws
def test_discovery_agent_excludes_tagged_resources():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    instances = ec2.run_instances(
        ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro"
    )
    instance_id = instances["Instances"][0]["InstanceId"]
    ec2.create_tags(Resources=[instance_id], Tags=[{"Key": "do-not-modify", "Value": "true"}])

    ctx = AgentContext(
        request=AssessmentRequest(
            customer_id="c1", account_id="123456789012", excluded_tags=["do-not-modify"]
        ),
        session=boto3.Session(region_name="us-east-1"),
        tools=ToolRegistry(),
        ai=AIFallback(enabled=False),
    )

    result = DiscoveryAgent().safe_run(ctx)

    ec2_findings = [f for f in result.findings if f.resource_id.startswith("i-")]
    assert ec2_findings == []


@mock_aws
def test_discovery_agent_flags_missing_environment_tag():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro")

    ctx = AgentContext(
        request=AssessmentRequest(customer_id="c1", account_id="123456789012"),
        session=boto3.Session(region_name="us-east-1"),
        tools=ToolRegistry(),
        ai=AIFallback(enabled=False),
    )

    result = DiscoveryAgent().safe_run(ctx)

    tagging_findings = [f for f in result.findings if f.resource_id == "tagging-compliance"]
    assert len(tagging_findings) == 1
    assert tagging_findings[0].estimated_monthly_savings == 0.0
    assert tagging_findings[0].ai_explanation  # generic recommendation always present
