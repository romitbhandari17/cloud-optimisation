from datetime import datetime, timedelta, timezone

import boto3
from moto import mock_aws

from cloudineer.core.ai.bedrock_client import AIFallback
from cloudineer.core.context import AgentContext
from cloudineer.core.contract import AssessmentRequest
from cloudineer.core.tools.base import ToolRegistry
from cloudineer.agents.compute_optimisation_agent import ComputeOptimisationAgent


def _ctx():
    return AgentContext(
        request=AssessmentRequest(customer_id="c1", account_id="123456789012"),
        session=boto3.Session(region_name="us-east-1"),
        tools=ToolRegistry(),
        ai=AIFallback(enabled=False),
    )


@mock_aws
def test_compute_optimisation_flags_idle_instance():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")

    instance = ec2.run_instances(
        ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.large"
    )["Instances"][0]
    instance_id = instance["InstanceId"]

    cloudwatch.put_metric_data(
        Namespace="AWS/EC2",
        MetricData=[
            {
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                "Timestamp": datetime.now(timezone.utc) - timedelta(days=1),
                "Value": 1.5,
                "Unit": "Percent",
            }
        ],
    )

    result = ComputeOptimisationAgent().safe_run(_ctx())

    assert not result.errors
    ec2_findings = [f for f in result.findings if f.resource_id == instance_id]
    assert len(ec2_findings) == 1
    assert ec2_findings[0].finding == "Idle EC2 instance"
    assert ec2_findings[0].estimated_monthly_savings > 0


@mock_aws
def test_compute_optimisation_flags_idle_ecs_service():
    ecs = boto3.client("ecs", region_name="us-east-1")
    cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")

    cluster = ecs.create_cluster(clusterName="demo-cluster")["cluster"]
    task_def = ecs.register_task_definition(
        family="demo-task",
        containerDefinitions=[{"name": "app", "image": "nginx", "memory": 256}],
    )["taskDefinition"]
    ecs.create_service(
        cluster=cluster["clusterArn"],
        serviceName="demo-service",
        taskDefinition=task_def["taskDefinitionArn"],
        desiredCount=2,
        launchType="FARGATE",
    )

    cloudwatch.put_metric_data(
        Namespace="AWS/ECS",
        MetricData=[
            {
                "MetricName": "CPUUtilization",
                "Dimensions": [
                    {"Name": "ClusterName", "Value": "demo-cluster"},
                    {"Name": "ServiceName", "Value": "demo-service"},
                ],
                "Timestamp": datetime.now(timezone.utc) - timedelta(days=1),
                "Value": 2.0,
                "Unit": "Percent",
            },
            {
                "MetricName": "MemoryUtilization",
                "Dimensions": [
                    {"Name": "ClusterName", "Value": "demo-cluster"},
                    {"Name": "ServiceName", "Value": "demo-service"},
                ],
                "Timestamp": datetime.now(timezone.utc) - timedelta(days=1),
                "Value": 3.0,
                "Unit": "Percent",
            },
        ],
    )

    result = ComputeOptimisationAgent().safe_run(_ctx())

    assert not result.errors
    ecs_findings = [f for f in result.findings if f.resource_id == "demo-cluster/demo-service"]
    assert len(ecs_findings) == 1
    assert ecs_findings[0].finding == "Idle ECS service"
    assert ecs_findings[0].estimated_monthly_savings > 0


@mock_aws
def test_compute_optimisation_flags_idle_lambda_function():
    iam = boto3.client("iam", region_name="us-east-1")
    role = iam.create_role(
        RoleName="lambda-role",
        AssumeRolePolicyDocument="{}",
    )["Role"]

    lambda_client = boto3.client("lambda", region_name="us-east-1")
    lambda_client.create_function(
        FunctionName="demo-function",
        Runtime="python3.12",
        Role=role["Arn"],
        Handler="index.handler",
        Code={"ZipFile": b"fake code"},
        MemorySize=128,
        Timeout=30,
    )

    # No put_metric_data call -> get_metric_statistics returns no datapoints,
    # which the agent treats as zero invocations (idle).
    result = ComputeOptimisationAgent().safe_run(_ctx())

    assert not result.errors
    lambda_findings = [f for f in result.findings if f.resource_id == "demo-function"]
    assert len(lambda_findings) == 1
    assert lambda_findings[0].finding == "Idle Lambda function"
    assert lambda_findings[0].estimated_monthly_savings > 0


@mock_aws
def test_compute_optimisation_flags_overprovisioned_lambda_memory():
    iam = boto3.client("iam", region_name="us-east-1")
    role = iam.create_role(
        RoleName="lambda-role",
        AssumeRolePolicyDocument="{}",
    )["Role"]

    lambda_client = boto3.client("lambda", region_name="us-east-1")
    cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")
    lambda_client.create_function(
        FunctionName="heavy-function",
        Runtime="python3.12",
        Role=role["Arn"],
        Handler="index.handler",
        Code={"ZipFile": b"fake code"},
        MemorySize=2048,
        Timeout=60,
    )

    cloudwatch.put_metric_data(
        Namespace="AWS/Lambda",
        MetricData=[
            {
                "MetricName": "Invocations",
                "Dimensions": [{"Name": "FunctionName", "Value": "heavy-function"}],
                "Timestamp": datetime.now(timezone.utc) - timedelta(days=1),
                "Value": 1000.0,
                "Unit": "Count",
            },
            {
                "MetricName": "Duration",
                "Dimensions": [{"Name": "FunctionName", "Value": "heavy-function"}],
                "Timestamp": datetime.now(timezone.utc) - timedelta(days=1),
                "Value": 500.0,  # 0.5s out of a 60s timeout -> well under the ratio threshold
                "Unit": "Milliseconds",
            },
        ],
    )

    result = ComputeOptimisationAgent().safe_run(_ctx())

    assert not result.errors
    findings = [f for f in result.findings if f.resource_id == "heavy-function"]
    assert len(findings) == 1
    assert findings[0].finding == "Possibly over-provisioned Lambda memory"
    assert findings[0].estimated_monthly_savings > 0
