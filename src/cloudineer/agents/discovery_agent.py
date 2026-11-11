"""Discovery Agent — discovers accounts, regions, services and resources.

docs/context1.txt agent #01 / docs/architecture.md Phase 1 priority 1. Pure Boto3,
deterministic: no AI is needed to enumerate what exists. The one exception is a
generic, deterministic tagging-compliance nudge (see ``_flag_tagging_gaps``): since
discovery findings never carry a dollar savings estimate, this keeps "AI
Opportunities" useful even on an account with zero cost-saving opportunities.
"""
from __future__ import annotations

import logging

from botocore.exceptions import BotoCoreError, ClientError

from cloudineer.core.agent import BaseAgent
from cloudineer.core.context import AgentContext
from cloudineer.core.contract import AgentResult, Finding, Risk

logger = logging.getLogger(__name__)

#: Tag key (case-insensitive) every resource is expected to carry for cost allocation.
REQUIRED_TAG_KEY = "environment"


class DiscoveryAgent(BaseAgent):
    name = "discovery"

    def run(self, ctx: AgentContext) -> AgentResult:
        result = AgentResult(agent=self.name, account_id=ctx.request.account_id)

        for region in ctx.request.regions:
            self._discover_ec2(ctx, region, result)
            self._discover_rds(ctx, region, result)

        self._discover_s3(ctx, result)
        self._flag_tagging_gaps(result)

        return result

    def _discover_ec2(self, ctx: AgentContext, region: str, result: AgentResult) -> None:
        try:
            ec2 = ctx.client("ec2", region_name=region)
            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate():
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        if instance.get("State", {}).get("Name") == "terminated":
                            continue
                        tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
                        if any(tag in ctx.request.excluded_tags for tag in tags):
                            continue
                        result.findings.append(
                            Finding(
                                resource_id=instance["InstanceId"],
                                finding=(
                                    f"EC2 instance discovered ({instance['InstanceType']}, "
                                    f"region={region})"
                                ),
                                evidence={
                                    "region": region,
                                    "instance_type": instance["InstanceType"],
                                    "state": instance["State"]["Name"],
                                    "tags": tags,
                                },
                                recommendation="Inventory only — no action required.",
                                risk=Risk.LOW,
                                approval_required=False,
                            )
                        )
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"EC2 discovery failed in {region}: {exc}")

    def _discover_rds(self, ctx: AgentContext, region: str, result: AgentResult) -> None:
        try:
            rds = ctx.client("rds", region_name=region)
            paginator = rds.get_paginator("describe_db_instances")
            for page in paginator.paginate():
                for db in page.get("DBInstances", []):
                    result.findings.append(
                        Finding(
                            resource_id=db["DBInstanceIdentifier"],
                            finding=(
                                f"RDS instance discovered ({db['DBInstanceClass']}, "
                                f"engine={db['Engine']}, region={region})"
                            ),
                            evidence={
                                "region": region,
                                "instance_class": db["DBInstanceClass"],
                                "engine": db["Engine"],
                                "status": db.get("DBInstanceStatus"),
                            },
                            recommendation="Inventory only — no action required.",
                            risk=Risk.LOW,
                            approval_required=False,
                        )
                    )
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"RDS discovery failed in {region}: {exc}")

    def _discover_s3(self, ctx: AgentContext, result: AgentResult) -> None:
        try:
            s3 = ctx.client("s3")
            for bucket in s3.list_buckets().get("Buckets", []):
                result.findings.append(
                    Finding(
                        resource_id=bucket["Name"],
                        finding="S3 bucket discovered",
                        evidence={"created": str(bucket.get("CreationDate"))},
                        recommendation="Inventory only — no action required.",
                        risk=Risk.LOW,
                        approval_required=False,
                    )
                )
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"S3 discovery failed: {exc}")

    def _flag_tagging_gaps(self, result: AgentResult) -> None:
        """Aggregate, deterministic governance nudge (see module docstring).

        Flags resources discovered without a REQUIRED_TAG_KEY tag so the dashboard
        always has an actionable, generic recommendation available, independent of
        whether any agent found a dollar-value savings opportunity this run.
        """
        missing = [
            f.resource_id
            for f in result.findings
            if "tags" in f.evidence
            and not any(key.lower() == REQUIRED_TAG_KEY for key in f.evidence["tags"])
        ]
        if not missing:
            return

        preview = ", ".join(missing[:5]) + ("..." if len(missing) > 5 else "")
        result.findings.append(
            Finding(
                resource_id="tagging-compliance",
                finding=f"{len(missing)} resource(s) missing a '{REQUIRED_TAG_KEY}' tag",
                evidence={"resource_ids": missing},
                recommendation=(
                    "Apply consistent environment/owner tags across all resources to "
                    "improve cost allocation, governance and automated policy enforcement."
                ),
                estimated_monthly_savings=0.0,
                risk=Risk.LOW,
                approval_required=False,
                ai_explanation=(
                    f"{len(missing)} resource(s) ({preview}) have no '{REQUIRED_TAG_KEY}' tag, "
                    "making it harder to attribute spend to teams/environments or enforce "
                    "tag-based cost allocation and automation policies."
                ),
            )
        )
