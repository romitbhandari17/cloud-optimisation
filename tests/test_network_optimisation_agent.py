from datetime import datetime, timedelta, timezone

import boto3
from moto import mock_aws

from cloudineer.agents.network_optimisation_agent import NetworkOptimisationAgent
from cloudineer.core.ai.bedrock_client import AIFallback
from cloudineer.core.context import AgentContext
from cloudineer.core.contract import AssessmentRequest
from cloudineer.core.tools.base import ToolRegistry


def _ctx() -> AgentContext:
    return AgentContext(
        request=AssessmentRequest(customer_id="c1", account_id="123456789012"),
        session=boto3.Session(region_name="us-east-1"),
        tools=ToolRegistry(),
        ai=AIFallback(enabled=False),
    )


@mock_aws
def test_network_optimisation_flags_idle_nat_gateway():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")

    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.0.0/24")["Subnet"]["SubnetId"]
    eip = ec2.allocate_address(Domain="vpc")["AllocationId"]
    nat = ec2.create_nat_gateway(SubnetId=subnet, AllocationId=eip)["NatGateway"]["NatGatewayId"]

    cloudwatch.put_metric_data(
        Namespace="AWS/NATGateway",
        MetricData=[
            {
                "MetricName": "BytesOutToDestination",
                "Dimensions": [{"Name": "NatGatewayId", "Value": nat}],
                "Timestamp": datetime.now(timezone.utc) - timedelta(days=1),
                "Value": 0.0,
                "Unit": "Bytes",
            }
        ],
    )

    result = NetworkOptimisationAgent().safe_run(_ctx())

    assert not result.errors
    nat_findings = [f for f in result.findings if f.resource_id == nat]
    assert len(nat_findings) == 1
    assert nat_findings[0].finding == "Idle NAT Gateway"
    assert nat_findings[0].estimated_monthly_savings > 0


@mock_aws
def test_network_optimisation_flags_unattached_elastic_ip():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    allocation = ec2.allocate_address(Domain="vpc")

    result = NetworkOptimisationAgent().safe_run(_ctx())

    assert not result.errors
    eip_findings = [
        f for f in result.findings if f.resource_id == allocation["AllocationId"]
    ]
    assert len(eip_findings) == 1
    assert eip_findings[0].finding == "Unattached Elastic IP address"
    assert eip_findings[0].estimated_monthly_savings > 0


@mock_aws
def test_network_optimisation_skips_attached_elastic_ip():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    reservation = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1)
    instance_id = reservation["Instances"][0]["InstanceId"]
    allocation = ec2.allocate_address(Domain="vpc")
    ec2.associate_address(InstanceId=instance_id, AllocationId=allocation["AllocationId"])

    result = NetworkOptimisationAgent().safe_run(_ctx())

    assert not result.errors
    eip_findings = [
        f for f in result.findings if f.resource_id == allocation["AllocationId"]
    ]
    assert len(eip_findings) == 0
