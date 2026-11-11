from datetime import datetime, timedelta, timezone

import boto3
from moto import mock_aws

from cloudineer.agents.db_optimisation_agent import DatabaseOptimisationAgent
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
def test_db_optimisation_flags_idle_rds_instance():
    rds = boto3.client("rds", region_name="us-east-1")
    cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")

    rds.create_db_instance(
        DBInstanceIdentifier="idle-db",
        DBInstanceClass="db.t3.medium",
        Engine="postgres",
        MasterUsername="admin",
        MasterUserPassword="password123",
        AllocatedStorage=20,
    )

    cloudwatch.put_metric_data(
        Namespace="AWS/RDS",
        MetricData=[
            {
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": "idle-db"}],
                "Timestamp": datetime.now(timezone.utc) - timedelta(days=1),
                "Value": 1.0,
                "Unit": "Percent",
            }
        ],
    )

    result = DatabaseOptimisationAgent().safe_run(_ctx())

    assert not result.errors
    idle_findings = [f for f in result.findings if f.resource_id == "idle-db"]
    assert len(idle_findings) == 1
    assert idle_findings[0].finding == "Idle RDS instance"
    assert idle_findings[0].estimated_monthly_savings > 0


@mock_aws
def test_db_optimisation_flags_multi_az_in_non_production():
    rds = boto3.client("rds", region_name="us-east-1")

    rds.create_db_instance(
        DBInstanceIdentifier="staging-db",
        DBInstanceClass="db.t3.medium",
        Engine="postgres",
        MasterUsername="admin",
        MasterUserPassword="password123",
        AllocatedStorage=20,
        MultiAZ=True,
        Tags=[{"Key": "environment", "Value": "staging"}],
    )

    result = DatabaseOptimisationAgent().safe_run(_ctx())

    assert not result.errors
    multi_az_findings = [
        f for f in result.findings if "Multi-AZ" in f.finding and f.resource_id == "staging-db"
    ]
    assert len(multi_az_findings) == 1
    assert multi_az_findings[0].estimated_monthly_savings > 0
