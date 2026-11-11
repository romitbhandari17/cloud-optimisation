import json

import boto3
from moto import mock_aws

from cloudineer.handlers import dashboard_handler, discovery_handler


@mock_aws
def test_discovery_handler_returns_agent_result_dict():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro")

    event = {
        "customer_config": {
            "customer_id": "c1",
            "account_id": "123456789012",
            "role_arn": None,
            "regions": ["us-east-1"],
        }
    }

    result = discovery_handler.handler(event, None)

    assert result["agent"] == "discovery"
    assert result["errors"] == []
    assert any(f["resource_id"].startswith("i-") for f in result["findings"])


@mock_aws
def test_discovery_handler_degrades_gracefully_on_invalid_event():
    # Missing the required `account_id` field -> pydantic validation error inside
    # build_context, which run_agent_handler must convert into a standard
    # AgentResult with `errors` populated, never raise out of the handler.
    event = {"customer_config": {"customer_id": "c1", "regions": ["us-east-1"]}}

    result = discovery_handler.handler(event, None)

    assert result["agent"] == "discovery"
    assert result["findings"] == []
    assert result["errors"]


@mock_aws
def test_dashboard_handler_aggregates_and_writes_report():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="cloudineer-reports-test")

    import os

    os.environ["CLOUDINEER_REPORTS_BUCKET"] = "cloudineer-reports-test"

    event = {
        "customer_config": {"customer_id": "c1", "account_id": "123456789012"},
        "agent_results": [
            {
                "agent": "compute-optimisation",
                "account_id": "123456789012",
                "findings": [
                    {
                        "resource_id": "i-1",
                        "finding": "Idle",
                        "recommendation": "Stop",
                        "estimated_monthly_savings": 100,
                        "risk": "high",
                        "approval_required": True,
                    }
                ],
                "errors": [],
            }
        ],
    }

    dashboard = dashboard_handler.handler(event, None)

    assert dashboard["potential_savings"]["total_monthly_usd"] == 100.0
    assert dashboard["report_location"].startswith("s3://cloudineer-reports-test/c1/")

    key = dashboard["report_location"].split("cloudineer-reports-test/", 1)[1]
    stored = json.loads(s3.get_object(Bucket="cloudineer-reports-test", Key=key)["Body"].read())
    assert stored["customer_id"] == "c1"

    del os.environ["CLOUDINEER_REPORTS_BUCKET"]
