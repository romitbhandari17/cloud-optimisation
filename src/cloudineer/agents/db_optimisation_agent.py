"""Database Optimisation Agent — identifies idle/underutilised RDS & Aurora.

docs/architecture.md §2 agent #04. Mirrors the EC2 Optimisation Agent's approach:
rule-based CloudWatch utilisation scoring first, with an AI fallback only for the
ambiguous "borderline" utilisation band. Covers:

  * Standalone RDS instances (MySQL/Postgres/etc.) — idle/underutilised CPU,
    and unnecessary Multi-AZ in non-production environments.
  * Aurora clusters (MySQL/Postgres compatible) — idle/underutilised CPU across
    all instances in the cluster, flagged as an Aurora Serverless v2 candidate.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from botocore.exceptions import BotoCoreError, ClientError

from cloudineer.core.agent import BaseAgent
from cloudineer.core.context import AgentContext
from cloudineer.core.contract import AgentResult, Finding, Risk

logger = logging.getLogger(__name__)

IDLE_CPU_THRESHOLD = 5.0            # percent: below this -> idle, high-confidence savings
UNDERUTILISED_CPU_THRESHOLD = 20.0  # percent: below this -> candidate for downsizing
BORDERLINE_BAND = (15.0, 25.0)      # percent: ambiguous zone where AI fallback is consulted

#: Rough, illustrative relative monthly cost by instance size step-down (USD placeholder).
#: A production deployment would source this from the Pricing API / Cost Explorer.
ESTIMATED_MONTHLY_COST_STEP = 90.0
#: Multi-AZ roughly doubles the instance-hour cost of a standalone RDS instance.
MULTI_AZ_MONTHLY_PREMIUM_ESTIMATE = 90.0
#: Non-production environment tags/values that make Multi-AZ unlikely to be required.
NON_PRODUCTION_ENVIRONMENTS = {"staging", "dev", "development", "test", "qa", "sandbox"}


class DatabaseOptimisationAgent(BaseAgent):
    name = "db-optimisation"

    def run(self, ctx: AgentContext) -> AgentResult:
        result = AgentResult(agent=self.name, account_id=ctx.request.account_id)

        for region in ctx.request.regions:
            self._analyse_rds_instances(ctx, region, result)
            self._analyse_aurora_clusters(ctx, region, result)

        return result

    # -- Standalone RDS instances ------------------------------------------------

    def _analyse_rds_instances(self, ctx: AgentContext, region: str, result: AgentResult) -> None:
        try:
            rds = ctx.client("rds", region_name=region)
            cloudwatch = ctx.client("cloudwatch", region_name=region)
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"RDS optimisation setup failed in {region}: {exc}")
            return

        try:
            instances = list(self._standalone_instances(rds, ctx.request.excluded_tags))
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Failed to list RDS instances in {region}: {exc}")
            return

        for db_id, db_class, engine, multi_az, tags in instances:
            try:
                avg_cpu = self._average_cpu(cloudwatch, "DBInstanceIdentifier", db_id, ctx.request.lookback_days)
            except (ClientError, BotoCoreError) as exc:
                result.errors.append(f"CloudWatch query failed for {db_id}: {exc}")
                continue

            if avg_cpu is not None:
                finding = self._evaluate_utilisation(
                    ctx,
                    resource_id=db_id,
                    region=region,
                    resource_class=db_class,
                    engine=engine,
                    avg_cpu=avg_cpu,
                    tags=tags,
                    resource_type="RDS instance",
                    recommendation="Downsize the instance class or stop it after owner confirmation.",
                )
                if finding:
                    result.findings.append(finding)

            multi_az_finding = self._evaluate_multi_az(db_id, region, multi_az, tags)
            if multi_az_finding:
                result.findings.append(multi_az_finding)

    @staticmethod
    def _standalone_instances(rds, excluded_tags: list[str]):
        paginator = rds.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page.get("DBInstances", []):
                if db.get("DBClusterIdentifier"):
                    continue  # part of an Aurora cluster — handled separately
                tags = {t["Key"]: t["Value"] for t in db.get("TagList", [])}
                if any(tag in excluded_tags for tag in tags):
                    continue
                yield (
                    db["DBInstanceIdentifier"],
                    db["DBInstanceClass"],
                    db["Engine"],
                    db.get("MultiAZ", False),
                    tags,
                )

    def _evaluate_multi_az(
        self, db_id: str, region: str, multi_az: bool, tags: dict
    ) -> Finding | None:
        if not multi_az:
            return None
        env_tag = (tags.get("environment") or tags.get("Environment") or "").lower()
        if env_tag not in NON_PRODUCTION_ENVIRONMENTS:
            return None
        return Finding(
            resource_id=db_id,
            finding=f"Multi-AZ enabled on a '{env_tag}' environment RDS instance",
            evidence={"region": region, "multi_az": True, "environment_tag": env_tag, "tags": tags},
            recommendation="Disable Multi-AZ for non-production databases to halve instance cost.",
            estimated_monthly_savings=MULTI_AZ_MONTHLY_PREMIUM_ESTIMATE,
            risk=Risk.LOW,
            approval_required=True,
        )

    # -- Aurora clusters ----------------------------------------------------------

    def _analyse_aurora_clusters(self, ctx: AgentContext, region: str, result: AgentResult) -> None:
        try:
            rds = ctx.client("rds", region_name=region)
            cloudwatch = ctx.client("cloudwatch", region_name=region)
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Aurora optimisation setup failed in {region}: {exc}")
            return

        try:
            clusters = list(self._aurora_clusters(rds, ctx.request.excluded_tags))
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Failed to list Aurora clusters in {region}: {exc}")
            return

        for cluster_id, engine, instance_ids, tags in clusters:
            cpu_samples = []
            for instance_id in instance_ids:
                try:
                    avg_cpu = self._average_cpu(
                        cloudwatch, "DBInstanceIdentifier", instance_id, ctx.request.lookback_days
                    )
                except (ClientError, BotoCoreError) as exc:
                    result.errors.append(f"CloudWatch query failed for {instance_id}: {exc}")
                    continue
                if avg_cpu is not None:
                    cpu_samples.append(avg_cpu)

            if not cpu_samples:
                continue

            cluster_avg_cpu = sum(cpu_samples) / len(cpu_samples)
            finding = self._evaluate_utilisation(
                ctx,
                resource_id=cluster_id,
                region=region,
                resource_class=f"{len(instance_ids)} instance(s)",
                engine=engine,
                avg_cpu=cluster_avg_cpu,
                tags=tags,
                resource_type="Aurora cluster",
                recommendation="Evaluate migrating to Aurora Serverless v2 to auto-scale with demand.",
            )
            if finding:
                result.findings.append(finding)

    @staticmethod
    def _aurora_clusters(rds, excluded_tags: list[str]):
        paginator = rds.get_paginator("describe_db_clusters")
        for page in paginator.paginate():
            for cluster in page.get("DBClusters", []):
                tags = {t["Key"]: t["Value"] for t in cluster.get("TagList", [])}
                if any(tag in excluded_tags for tag in tags):
                    continue
                instance_ids = [m["DBInstanceIdentifier"] for m in cluster.get("DBClusterMembers", [])]
                yield cluster["DBClusterIdentifier"], cluster["Engine"], instance_ids, tags

    # -- Shared utilisation scoring -------------------------------------------------

    @staticmethod
    def _average_cpu(cloudwatch, dimension_name: str, resource_id: str, lookback_days: int) -> float | None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)
        response = cloudwatch.get_metric_statistics(
            Namespace="AWS/RDS",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": dimension_name, "Value": resource_id}],
            StartTime=start,
            EndTime=end,
            Period=86400,
            Statistics=["Average"],
        )
        datapoints = response.get("Datapoints", [])
        if not datapoints:
            return None
        return sum(d["Average"] for d in datapoints) / len(datapoints)

    def _evaluate_utilisation(
        self,
        ctx: AgentContext,
        *,
        resource_id: str,
        region: str,
        resource_class: str,
        engine: str,
        avg_cpu: float,
        tags: dict,
        resource_type: str,
        recommendation: str,
    ) -> Finding | None:
        evidence = {
            "region": region,
            "instance_class": resource_class,
            "engine": engine,
            "average_cpu_percent": round(avg_cpu, 2),
            "period_days": ctx.request.lookback_days,
            "tags": tags,
        }

        if avg_cpu < IDLE_CPU_THRESHOLD:
            return Finding(
                resource_id=resource_id,
                finding=f"Idle {resource_type}",
                evidence=evidence,
                recommendation=recommendation,
                estimated_monthly_savings=ESTIMATED_MONTHLY_COST_STEP * 2,
                risk=Risk.MEDIUM,
                approval_required=True,
            )

        if BORDERLINE_BAND[0] <= avg_cpu <= BORDERLINE_BAND[1]:
            ai_result = ctx.ai.classify_savings_opportunity(evidence=evidence)
            if ai_result:
                return Finding(
                    resource_id=resource_id,
                    finding=f"Borderline-utilised {resource_type} (AI-assisted)",
                    evidence=evidence,
                    recommendation=ai_result.get("recommendation", recommendation),
                    estimated_monthly_savings=ESTIMATED_MONTHLY_COST_STEP,
                    risk=Risk(ai_result.get("risk", "medium")),
                    approval_required=True,
                )
            # AI unavailable: fall through to the deterministic rule below.

        if avg_cpu < UNDERUTILISED_CPU_THRESHOLD:
            return Finding(
                resource_id=resource_id,
                finding=f"Underutilised {resource_type}",
                evidence=evidence,
                recommendation=recommendation,
                estimated_monthly_savings=ESTIMATED_MONTHLY_COST_STEP,
                risk=Risk.MEDIUM,
                approval_required=True,
            )

        return None
