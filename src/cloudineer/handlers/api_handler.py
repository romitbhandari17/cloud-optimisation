"""Dashboard UI API Lambda — backs the static dashboard under ui/.

Exposed behind an API Gateway REST API ({proxy+} -> ANY -> this Lambda, see
terraform/modules/api). Routes:

    GET  /customers              -> list onboarded customers (from the bundled
                                     config/customers/*.yaml files)
    GET  /reports?customer_id=.. -> list generated Assessment Dashboard reports
                                     in the central reports S3 bucket
    GET  /reports/{key}          -> fetch one report's JSON body
    POST /assessments            -> start a new Step Functions execution for a
                                     customer, body: {"customer_id": "..."}

CORS is handled inline (Access-Control-Allow-Origin: *) since this is an
internal tool with no auth in front of it yet.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import boto3
import yaml

logger = logging.getLogger()
logger.setLevel(logging.INFO)

#: Set by Terraform (terraform/modules/api) to the central reports bucket.
REPORTS_BUCKET_ENV_VAR = "CLOUDINEER_REPORTS_BUCKET"
#: Set by Terraform (terraform/modules/api) to the assessment state machine ARN.
STATE_MACHINE_ARN_ENV_VAR = "CLOUDINEER_STATE_MACHINE_ARN"
#: Directory the build script bundles config/customers/*.yaml into (see
#: scripts/build_lambda_artifacts.sh).
CONFIG_DIR_ENV_VAR = "CLOUDINEER_CONFIG_DIR"

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def _config_dir() -> Path:
    return Path(os.environ.get(CONFIG_DIR_ENV_VAR, "/var/task/config/customers"))


def _response(status: int, body: Any) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {**_CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _load_customer_config(customer_id: str) -> dict[str, Any] | None:
    path = _config_dir() / f"{customer_id}.yaml"
    if not path.is_file():
        return None
    return yaml.safe_load(path.read_text())


def list_customers() -> dict[str, Any]:
    customers = []
    config_dir = _config_dir()
    if config_dir.is_dir():
        for path in sorted(config_dir.glob("*.yaml")):
            config = yaml.safe_load(path.read_text())
            customers.append(
                {
                    "customer_id": config.get("customer_id", path.stem),
                    "account_id": config.get("account_id"),
                    "regions": config.get("regions", []),
                    "environment": config.get("environment", []),
                    "enabled_agents": config.get("enabled_agents", []),
                }
            )
    return _response(200, {"customers": customers})


def list_reports(query: dict[str, str]) -> dict[str, Any]:
    bucket = os.environ.get(REPORTS_BUCKET_ENV_VAR)
    if not bucket:
        return _response(500, {"message": f"{REPORTS_BUCKET_ENV_VAR} is not set"})

    customer_id = query.get("customer_id")
    prefix = f"{customer_id}/" if customer_id else ""

    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    reports = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            parts = key.split("/", 1)
            reports.append(
                {
                    "key": key,
                    "customer_id": parts[0] if len(parts) == 2 else None,
                    "last_modified": obj["LastModified"],
                    "size_bytes": obj["Size"],
                }
            )
    reports.sort(key=lambda r: r["last_modified"], reverse=True)
    return _response(200, {"reports": reports})


def get_report(key: str) -> dict[str, Any]:
    bucket = os.environ.get(REPORTS_BUCKET_ENV_VAR)
    if not bucket:
        return _response(500, {"message": f"{REPORTS_BUCKET_ENV_VAR} is not set"})

    s3 = boto3.client("s3")
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except s3.exceptions.NoSuchKey:
        return _response(404, {"message": f"No such report: {key}"})
    return _response(200, json.loads(obj["Body"].read()))


def start_assessment(body: dict[str, Any]) -> dict[str, Any]:
    state_machine_arn = os.environ.get(STATE_MACHINE_ARN_ENV_VAR)
    if not state_machine_arn:
        return _response(500, {"message": f"{STATE_MACHINE_ARN_ENV_VAR} is not set"})

    customer_id = body.get("customer_id")
    if not customer_id:
        return _response(400, {"message": "customer_id is required"})

    customer_config = _load_customer_config(customer_id)
    if customer_config is None:
        return _response(404, {"message": f"Unknown customer_id: {customer_id}"})

    sfn = boto3.client("stepfunctions")
    execution_name = f"{customer_id}-{int(time.time())}"
    result = sfn.start_execution(
        stateMachineArn=state_machine_arn,
        name=execution_name,
        input=json.dumps({"customer_config": customer_config}),
    )
    return _response(
        202,
        {
            "execution_arn": result["executionArn"],
            "start_date": result["startDate"],
            "customer_id": customer_id,
        },
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = event.get("httpMethod", "GET")
    path = event.get("path", "/")
    query = event.get("queryStringParameters") or {}

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": _CORS_HEADERS, "body": ""}

    try:
        if method == "GET" and path == "/customers":
            return list_customers()
        if method == "GET" and path == "/reports":
            return list_reports(query)
        if method == "GET" and path.startswith("/reports/"):
            return get_report(path[len("/reports/") :])
        if method == "POST" and path == "/assessments":
            body = json.loads(event.get("body") or "{}")
            return start_assessment(body)
        return _response(404, {"message": f"No route for {method} {path}"})
    except Exception as exc:  # noqa: BLE001 - always return a JSON error, never crash
        logger.exception("Unhandled error in api_handler")
        return _response(500, {"message": str(exc)})
