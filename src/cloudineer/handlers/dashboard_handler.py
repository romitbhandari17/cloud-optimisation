"""Dashboard Lambda — the final Step Functions state.

Receives the outputs of the parallel agent branches plus the original
``customer_config``, builds the Assessment Dashboard (docs/architecture.md §7),
writes it to the central reports S3 bucket, and returns it.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3

from cloudineer.core.contract import AgentResult
from cloudineer.reports.dashboard_builder import build_dashboard

logger = logging.getLogger()
logger.setLevel(logging.INFO)

#: Set by Terraform (terraform/compute) to the central-platform reports bucket.
REPORTS_BUCKET_ENV_VAR = "CLOUDINEER_REPORTS_BUCKET"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Expected event shape (produced by the Step Functions Parallel state):

        {
          "customer_config": {...},
          "agent_results": [<AgentResult JSON>, <AgentResult JSON>, ...]
        }
    """
    customer_config = event["customer_config"]
    agent_results = [AgentResult.model_validate(r) for r in event.get("agent_results", [])]

    dashboard = build_dashboard(
        customer_id=customer_config["customer_id"],
        account_id=customer_config["account_id"],
        results=agent_results,
    )

    bucket = os.environ.get(REPORTS_BUCKET_ENV_VAR)
    if bucket:
        key = (
            f"{customer_config['customer_id']}/"
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S')}.json"
        )
        try:
            boto3.client("s3").put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(dashboard, default=str).encode("utf-8"),
                ContentType="application/json",
            )
            dashboard["report_location"] = f"s3://{bucket}/{key}"
        except Exception as exc:  # noqa: BLE001 - never fail the assessment over reporting
            logger.exception("Failed to write dashboard report to S3")
            dashboard.setdefault("errors", []).append(f"ReportWriteFailed: {exc}")
    else:
        logger.warning(
            "%s not set — dashboard JSON returned inline only, not persisted",
            REPORTS_BUCKET_ENV_VAR,
        )

    return dashboard
