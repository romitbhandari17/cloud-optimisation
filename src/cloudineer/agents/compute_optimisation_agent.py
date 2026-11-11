"""Compute Optimisation Agent — identifies idle/underutilised compute across

EC2, ECS and Lambda. docs/context1.txt agent #03 / docs/architecture.md Phase 1
priority 3 (originally "EC2 Optimisation", broadened to cover every compute
surface under one agent). Utilisation scoring is rule-based (CloudWatch metrics
over the lookback window) for all three compute types. The AI fallback is only
consulted for EC2 instances that fall into a borderline band where a simple
threshold isn't a confident enough signal on its own.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from botocore.exceptions import BotoCoreError, ClientError

from cloudineer.core.agent import BaseAgent
from cloudineer.core.context import AgentContext
from cloudineer.core.contract import AgentResult, Finding, Risk

logger = logging.getLogger(__name__)

IDLE_CPU_THRESHOLD = 5.0       # percent: below this -> idle, high risk-free savings
UNDERUTILISED_CPU_THRESHOLD = 20.0  # percent: below this -> candidate for downsizing
BORDERLINE_BAND = (15.0, 25.0)  # percent: ambiguous zone where AI fallback is consulted

# Rough, illustrative relative monthly cost by instance size step-down (USD placeholder).
# A production deployment would source this from the Pricing API / Cost Explorer.
ESTIMATED_MONTHLY_COST_BY_FAMILY_STEP = 60.0

# ECS service utilisation thresholds (checked on both CPU and memory; either one
# running idle/underutilised is enough to flag the service for a task-count/size review).
ECS_IDLE_UTILISATION_THRESHOLD = 10.0
ECS_UNDERUTILISED_THRESHOLD = 30.0
ECS_ESTIMATED_MONTHLY_COST_PER_TASK_STEP = 40.0

# Lambda thresholds. Total invocations below this over the lookback window -> idle.
LAMBDA_IDLE_INVOCATION_THRESHOLD = 1
# Average duration under this fraction of the configured timeout, on a function with
# non-trivial memory allocated, suggests the memory (and therefore cost-per-ms) is
# higher than the workload needs (Lambda is billed on memory x duration).
LAMBDA_DURATION_TO_TIMEOUT_RATIO_THRESHOLD = 0.10
LAMBDA_MIN_MEMORY_MB_FOR_REVIEW = 512
LAMBDA_ESTIMATED_MONTHLY_SAVINGS_IDLE = 20.0
LAMBDA_ESTIMATED_MONTHLY_SAVINGS_OVERPROVISIONED = 15.0


class ComputeOptimisationAgent(BaseAgent):
    name = "compute-optimisation"

    def run(self, ctx: AgentContext) -> AgentResult:
        result = AgentResult(agent=self.name, account_id=ctx.request.account_id)

        for region in ctx.request.regions:
            self._analyse_region(ctx, region, result)
            self._analyse_ecs_region(ctx, region, result)
            self._analyse_lambda_region(ctx, region, result)

        return result

    # -- EC2 instances ----------------------------------------------------------

    def _analyse_region(self, ctx: AgentContext, region: str, result: AgentResult) -> None:
        try:
            ec2 = ctx.client("ec2", region_name=region)
            cloudwatch = ctx.client("cloudwatch", region_name=region)
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"EC2 optimisation setup failed in {region}: {exc}")
            return

        try:
            instances = self._running_instances(ec2, ctx.request.excluded_tags)
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Failed to list EC2 instances in {region}: {exc}")
            return

        for instance_id, instance_type, tags in instances:
            try:
                avg_cpu = self._average_metric(
                    cloudwatch, "AWS/EC2", "CPUUtilization", "InstanceId", instance_id, ctx.request.lookback_days
                )
            except (ClientError, BotoCoreError) as exc:
                result.errors.append(f"CloudWatch query failed for {instance_id}: {exc}")
                continue

            if avg_cpu is None:
                continue  # no metric data yet (e.g. brand new instance)

            finding = self._evaluate(ctx, region, instance_id, instance_type, avg_cpu, tags)
            if finding:
                result.findings.append(finding)

    @staticmethod
    def _running_instances(ec2, excluded_tags: list[str]):
        paginator = ec2.get_paginator("describe_instances")
        for page in paginator.paginate(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        ):
            for reservation in page.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
                    if any(tag in excluded_tags for tag in tags):
                        continue
                    yield instance["InstanceId"], instance["InstanceType"], tags

    def _evaluate(
        self,
        ctx: AgentContext,
        region: str,
        instance_id: str,
        instance_type: str,
        avg_cpu: float,
        tags: dict,
    ) -> Finding | None:
        evidence = {
            "region": region,
            "instance_type": instance_type,
            "average_cpu_percent": round(avg_cpu, 2),
            "period_days": ctx.request.lookback_days,
            "tags": tags,
        }

        if avg_cpu < IDLE_CPU_THRESHOLD:
            return Finding(
                resource_id=instance_id,
                finding="Idle EC2 instance",
                evidence=evidence,
                recommendation="Stop or terminate after owner confirmation.",
                estimated_monthly_savings=ESTIMATED_MONTHLY_COST_BY_FAMILY_STEP * 2,
                risk=Risk.MEDIUM,
                approval_required=True,
            )

        if BORDERLINE_BAND[0] <= avg_cpu <= BORDERLINE_BAND[1]:
            ai_result = ctx.ai.classify_savings_opportunity(evidence=evidence)
            if ai_result:
                return Finding(
                    resource_id=instance_id,
                    finding="Borderline-utilised EC2 instance (AI-assisted)",
                    evidence=evidence,
                    recommendation=ai_result.get(
                        "recommendation", "Evaluate downsizing with workload owner."
                    ),
                    estimated_monthly_savings=ESTIMATED_MONTHLY_COST_BY_FAMILY_STEP,
                    risk=Risk(ai_result.get("risk", "medium")),
                    approval_required=True,
                )
            # AI unavailable: fall through to the deterministic rule below.

        if avg_cpu < UNDERUTILISED_CPU_THRESHOLD:
            return Finding(
                resource_id=instance_id,
                finding="Underutilised EC2 instance",
                evidence=evidence,
                recommendation="Evaluate downsizing to a smaller instance size.",
                estimated_monthly_savings=ESTIMATED_MONTHLY_COST_BY_FAMILY_STEP,
                risk=Risk.MEDIUM,
                approval_required=True,
            )

        return None

    # -- ECS services -------------------------------------------------------------

    def _analyse_ecs_region(self, ctx: AgentContext, region: str, result: AgentResult) -> None:
        try:
            ecs = ctx.client("ecs", region_name=region)
            cloudwatch = ctx.client("cloudwatch", region_name=region)
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"ECS optimisation setup failed in {region}: {exc}")
            return

        try:
            services = list(self._ecs_services(ecs))
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Failed to list ECS services in {region}: {exc}")
            return

        for cluster_name, service_name, desired_count, launch_type in services:
            if desired_count == 0:
                continue  # already scaled to zero — nothing to optimise

            try:
                avg_cpu = self._average_metric(
                    cloudwatch, "AWS/ECS", "CPUUtilization", "ClusterName", cluster_name,
                    ctx.request.lookback_days, extra_dimensions={"ServiceName": service_name},
                )
                avg_memory = self._average_metric(
                    cloudwatch, "AWS/ECS", "MemoryUtilization", "ClusterName", cluster_name,
                    ctx.request.lookback_days, extra_dimensions={"ServiceName": service_name},
                )
            except (ClientError, BotoCoreError) as exc:
                result.errors.append(f"CloudWatch query failed for ECS service {service_name}: {exc}")
                continue

            if avg_cpu is None and avg_memory is None:
                continue  # no metric data yet

            finding = self._evaluate_ecs_service(
                region, cluster_name, service_name, desired_count, launch_type, avg_cpu, avg_memory
            )
            if finding:
                result.findings.append(finding)

    @staticmethod
    def _ecs_services(ecs):
        cluster_paginator = ecs.get_paginator("list_clusters")
        for cluster_page in cluster_paginator.paginate():
            for cluster_arn in cluster_page.get("clusterArns", []):
                service_paginator = ecs.get_paginator("list_services")
                for service_page in service_paginator.paginate(cluster=cluster_arn):
                    service_arns = service_page.get("serviceArns", [])
                    if not service_arns:
                        continue
                    # describe_services is capped at 10 ARNs per call.
                    for i in range(0, len(service_arns), 10):
                        batch = service_arns[i : i + 10]
                        details = ecs.describe_services(cluster=cluster_arn, services=batch)
                        for service in details.get("services", []):
                            yield (
                                cluster_arn.split("/")[-1],
                                service["serviceName"],
                                service.get("desiredCount", 0),
                                service.get("launchType", "FARGATE"),
                            )

    def _evaluate_ecs_service(
        self,
        region: str,
        cluster_name: str,
        service_name: str,
        desired_count: int,
        launch_type: str,
        avg_cpu: float | None,
        avg_memory: float | None,
    ) -> Finding | None:
        # Use whichever metrics are present; treat a missing metric as "not a blocker".
        utilisations = [v for v in (avg_cpu, avg_memory) if v is not None]
        worst = min(utilisations) if utilisations else None
        if worst is None:
            return None

        evidence = {
            "region": region,
            "cluster": cluster_name,
            "desired_count": desired_count,
            "launch_type": launch_type,
            "average_cpu_percent": round(avg_cpu, 2) if avg_cpu is not None else None,
            "average_memory_percent": round(avg_memory, 2) if avg_memory is not None else None,
        }

        if worst < ECS_IDLE_UTILISATION_THRESHOLD:
            return Finding(
                resource_id=f"{cluster_name}/{service_name}",
                finding="Idle ECS service",
                evidence=evidence,
                recommendation="Reduce desired task count or scale the service to zero after owner confirmation.",
                estimated_monthly_savings=ECS_ESTIMATED_MONTHLY_COST_PER_TASK_STEP * desired_count * 2,
                risk=Risk.MEDIUM,
                approval_required=True,
            )

        if worst < ECS_UNDERUTILISED_THRESHOLD:
            return Finding(
                resource_id=f"{cluster_name}/{service_name}",
                finding="Underutilised ECS service",
                evidence=evidence,
                recommendation="Reduce task CPU/memory reservation or desired task count.",
                estimated_monthly_savings=ECS_ESTIMATED_MONTHLY_COST_PER_TASK_STEP * desired_count,
                risk=Risk.MEDIUM,
                approval_required=True,
            )

        return None

    # -- Lambda functions ---------------------------------------------------------

    def _analyse_lambda_region(self, ctx: AgentContext, region: str, result: AgentResult) -> None:
        try:
            lambda_client = ctx.client("lambda", region_name=region)
            cloudwatch = ctx.client("cloudwatch", region_name=region)
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Lambda optimisation setup failed in {region}: {exc}")
            return

        try:
            functions = list(self._lambda_functions(lambda_client))
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Failed to list Lambda functions in {region}: {exc}")
            return

        for function_name, memory_size, timeout_seconds in functions:
            try:
                total_invocations = self._sum_metric(
                    cloudwatch, "Invocations", function_name, ctx.request.lookback_days
                )
                avg_duration_ms = self._average_metric(
                    cloudwatch, "AWS/Lambda", "Duration", "FunctionName", function_name, ctx.request.lookback_days
                )
            except (ClientError, BotoCoreError) as exc:
                result.errors.append(f"CloudWatch query failed for Lambda function {function_name}: {exc}")
                continue

            finding = self._evaluate_lambda(
                region, function_name, memory_size, timeout_seconds, total_invocations, avg_duration_ms
            )
            if finding:
                result.findings.append(finding)

    @staticmethod
    def _lambda_functions(lambda_client):
        # Note: unlike EC2/RDS/ECS, this doesn't honour excluded_tags — list_functions
        # doesn't return tags inline and tagging-based filtering would need an extra
        # lambda:ListTags call per function, which isn't in the customer-role policy yet.
        paginator = lambda_client.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                yield fn["FunctionName"], fn.get("MemorySize", 128), fn.get("Timeout", 3)

    @staticmethod
    def _sum_metric(cloudwatch, metric_name: str, function_name: str, lookback_days: int) -> float | None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)
        response = cloudwatch.get_metric_statistics(
            Namespace="AWS/Lambda",
            MetricName=metric_name,
            Dimensions=[{"Name": "FunctionName", "Value": function_name}],
            StartTime=start,
            EndTime=end,
            Period=86400,
            Statistics=["Sum"],
        )
        datapoints = response.get("Datapoints", [])
        if not datapoints:
            return 0.0
        return sum(d["Sum"] for d in datapoints)

    def _evaluate_lambda(
        self,
        region: str,
        function_name: str,
        memory_size: int,
        timeout_seconds: int,
        total_invocations: float | None,
        avg_duration_ms: float | None,
    ) -> Finding | None:
        evidence = {
            "region": region,
            "memory_mb": memory_size,
            "timeout_seconds": timeout_seconds,
            "total_invocations": total_invocations,
            "average_duration_ms": round(avg_duration_ms, 2) if avg_duration_ms is not None else None,
        }

        if total_invocations is not None and total_invocations < LAMBDA_IDLE_INVOCATION_THRESHOLD:
            return Finding(
                resource_id=function_name,
                finding="Idle Lambda function",
                evidence=evidence,
                recommendation="Review whether this function is still needed; remove or archive after owner confirmation.",
                estimated_monthly_savings=LAMBDA_ESTIMATED_MONTHLY_SAVINGS_IDLE,
                risk=Risk.LOW,
                approval_required=True,
            )

        if (
            avg_duration_ms is not None
            and memory_size >= LAMBDA_MIN_MEMORY_MB_FOR_REVIEW
            and timeout_seconds > 0
            and (avg_duration_ms / 1000) / timeout_seconds < LAMBDA_DURATION_TO_TIMEOUT_RATIO_THRESHOLD
        ):
            return Finding(
                resource_id=function_name,
                finding="Possibly over-provisioned Lambda memory",
                evidence=evidence,
                recommendation=(
                    "Actual duration is a small fraction of the configured timeout at "
                    f"{memory_size}MB memory; review with AWS Lambda Power Tuning."
                ),
                estimated_monthly_savings=LAMBDA_ESTIMATED_MONTHLY_SAVINGS_OVERPROVISIONED,
                risk=Risk.LOW,
                approval_required=True,
            )

        return None

    # -- Shared CloudWatch helper ---------------------------------------------------

    @staticmethod
    def _average_metric(
        cloudwatch,
        namespace: str,
        metric_name: str,
        dimension_name: str,
        dimension_value: str,
        lookback_days: int,
        *,
        extra_dimensions: dict | None = None,
    ) -> float | None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)
        dimensions = [{"Name": dimension_name, "Value": dimension_value}]
        for name, value in (extra_dimensions or {}).items():
            dimensions.append({"Name": name, "Value": value})
        response = cloudwatch.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start,
            EndTime=end,
            Period=86400,
            Statistics=["Average"],
        )
        datapoints = response.get("Datapoints", [])
        if not datapoints:
            return None
        return sum(d["Average"] for d in datapoints) / len(datapoints)
