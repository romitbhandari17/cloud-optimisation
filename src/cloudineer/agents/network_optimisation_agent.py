"""Network Optimisation Agent — NAT Gateway, load balancer, Elastic IP and data-transfer checks.

docs/context.txt "Step 6. Networking Cost Optimisation" (NAT Gateway expenditure,
cross-AZ/inter-region data transfer, load balancer utilisation, VPC endpoints are
"often overlooked"). This agent is rule-based only — networking waste (idle NAT
Gateways, unused load balancers, unattached Elastic IPs) is unambiguous enough that
no AI fallback is needed. Covers:

  * NAT Gateways with near-zero bytes processed over the lookback window.
  * Application/Network Load Balancers with zero/near-zero request or flow volume.
  * Unattached (reserved but unused) Elastic IP addresses.
  * Cost Explorer-reported data-transfer spend (cross-AZ, inter-region, internet) —
    informational only, surfaced so it isn't missed in the per-service cost breakdown.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from botocore.exceptions import BotoCoreError, ClientError

from cloudineer.core.agent import BaseAgent
from cloudineer.core.context import AgentContext
from cloudineer.core.contract import AgentResult, Finding, Risk

logger = logging.getLogger(__name__)

IDLE_BYTES_THRESHOLD = 1_000_000  # bytes processed over the whole lookback window
IDLE_REQUEST_THRESHOLD = 1        # request/flow count over the whole lookback window

#: Rough, illustrative monthly cost placeholders (USD). A production deployment
#: would source these from the Pricing API rather than hardcoding them.
ESTIMATED_NAT_GATEWAY_MONTHLY_COST = 33.0   # ~$0.045/hr base charge
ESTIMATED_LOAD_BALANCER_MONTHLY_COST = 18.0  # ~$0.0225-0.025/hr base charge (ALB/NLB)
ESTIMATED_ELASTIC_IP_MONTHLY_COST = 3.6      # charged hourly once unattached

#: Cost Explorer USAGE_TYPE substrings that represent network data-transfer spend.
DATA_TRANSFER_USAGE_MARKERS = ("DataTransfer", "-In-Bytes", "-Out-Bytes", "-Regional-Bytes")
#: Flag data-transfer spend as a finding once it reaches this share of total cost.
SIGNIFICANT_DATA_TRANSFER_SHARE = 0.05


class NetworkOptimisationAgent(BaseAgent):
    name = "network-optimisation"

    def run(self, ctx: AgentContext) -> AgentResult:
        result = AgentResult(agent=self.name, account_id=ctx.request.account_id)

        for region in ctx.request.regions:
            self._analyse_nat_gateways(ctx, region, result)
            self._analyse_load_balancers(ctx, region, result)
            self._analyse_elastic_ips(ctx, region, result)

        self._analyse_data_transfer(ctx, result)

        return result

    # -- NAT Gateways --------------------------------------------------------------

    def _analyse_nat_gateways(self, ctx: AgentContext, region: str, result: AgentResult) -> None:
        try:
            ec2 = ctx.client("ec2", region_name=region)
            cloudwatch = ctx.client("cloudwatch", region_name=region)
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"NAT Gateway setup failed in {region}: {exc}")
            return

        try:
            gateways = list(self._nat_gateways(ec2, ctx.request.excluded_tags))
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Failed to list NAT Gateways in {region}: {exc}")
            return

        for nat_id, vpc_id, tags in gateways:
            try:
                bytes_out = self._sum_metric(
                    cloudwatch, "AWS/NATGateway", "BytesOutToDestination", "NatGatewayId", nat_id,
                    ctx.request.lookback_days,
                )
                bytes_in = self._sum_metric(
                    cloudwatch, "AWS/NATGateway", "BytesInFromSource", "NatGatewayId", nat_id,
                    ctx.request.lookback_days,
                )
            except (ClientError, BotoCoreError) as exc:
                result.errors.append(f"CloudWatch query failed for NAT Gateway {nat_id}: {exc}")
                continue

            total_bytes = (bytes_out or 0.0) + (bytes_in or 0.0)
            if total_bytes >= IDLE_BYTES_THRESHOLD:
                continue

            result.findings.append(
                Finding(
                    resource_id=nat_id,
                    finding="Idle NAT Gateway",
                    evidence={
                        "region": region,
                        "vpc_id": vpc_id,
                        "bytes_processed": round(total_bytes, 2),
                        "period_days": ctx.request.lookback_days,
                        "tags": tags,
                    },
                    recommendation=(
                        "Confirm no workload depends on this NAT Gateway, then delete it "
                        "and release its Elastic IP. If outbound internet access is still "
                        "required, consider a single shared NAT Gateway per AZ instead."
                    ),
                    estimated_monthly_savings=ESTIMATED_NAT_GATEWAY_MONTHLY_COST,
                    risk=Risk.MEDIUM,
                    approval_required=True,
                )
            )

    @staticmethod
    def _nat_gateways(ec2, excluded_tags: list[str]):
        paginator = ec2.get_paginator("describe_nat_gateways")
        for page in paginator.paginate(Filter=[{"Name": "state", "Values": ["available"]}]):
            for nat in page.get("NatGateways", []):
                tags = {t["Key"]: t["Value"] for t in nat.get("Tags", [])}
                if any(tag in excluded_tags for tag in tags):
                    continue
                yield nat["NatGatewayId"], nat.get("VpcId", ""), tags

    # -- Load Balancers --------------------------------------------------------------

    def _analyse_load_balancers(self, ctx: AgentContext, region: str, result: AgentResult) -> None:
        try:
            elbv2 = ctx.client("elbv2", region_name=region)
            cloudwatch = ctx.client("cloudwatch", region_name=region)
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Load balancer setup failed in {region}: {exc}")
            return

        try:
            balancers = list(self._load_balancers(elbv2, ctx.request.excluded_tags))
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Failed to list load balancers in {region}: {exc}")
            return

        for lb_name, lb_arn, lb_type, tags in balancers:
            metric_name = "RequestCount" if lb_type == "application" else "ActiveFlowCount"
            dimension_value = "/".join(lb_arn.split("/")[-3:])  # e.g. app/my-lb/abc123

            try:
                volume = self._sum_metric(
                    cloudwatch, "AWS/ApplicationELB" if lb_type == "application" else "AWS/NetworkELB",
                    metric_name, "LoadBalancer", dimension_value, ctx.request.lookback_days,
                )
            except (ClientError, BotoCoreError) as exc:
                result.errors.append(f"CloudWatch query failed for load balancer {lb_name}: {exc}")
                continue

            if (volume or 0.0) >= IDLE_REQUEST_THRESHOLD:
                continue

            result.findings.append(
                Finding(
                    resource_id=lb_name,
                    finding=f"Unused {lb_type.upper() if lb_type == 'nlb' else lb_type.title()} Load Balancer",
                    evidence={
                        "region": region,
                        "type": lb_type,
                        "metric": metric_name,
                        "total_over_period": round(volume or 0.0, 2),
                        "period_days": ctx.request.lookback_days,
                        "tags": tags,
                    },
                    recommendation=(
                        "Confirm no listener/target group is still in use, then delete "
                        "this load balancer to stop the hourly base charge."
                    ),
                    estimated_monthly_savings=ESTIMATED_LOAD_BALANCER_MONTHLY_COST,
                    risk=Risk.MEDIUM,
                    approval_required=True,
                )
            )

    @staticmethod
    def _load_balancers(elbv2, excluded_tags: list[str]):
        paginator = elbv2.get_paginator("describe_load_balancers")
        arns_and_names = []
        for page in paginator.paginate():
            for lb in page.get("LoadBalancers", []):
                arns_and_names.append((lb["LoadBalancerArn"], lb["LoadBalancerName"], lb["Type"]))

        if not arns_and_names:
            return

        # describe_tags accepts up to 20 ARNs per call.
        tags_by_arn: dict[str, dict] = {}
        arns = [arn for arn, _, _ in arns_and_names]
        for i in range(0, len(arns), 20):
            batch = arns[i : i + 20]
            response = elbv2.describe_tags(ResourceArns=batch)
            for description in response.get("TagDescriptions", []):
                tags_by_arn[description["ResourceArn"]] = {
                    t["Key"]: t["Value"] for t in description.get("Tags", [])
                }

        for arn, name, lb_type in arns_and_names:
            tags = tags_by_arn.get(arn, {})
            if any(tag in excluded_tags for tag in tags):
                continue
            yield name, arn, lb_type, tags

    # -- Elastic IPs --------------------------------------------------------------

    def _analyse_elastic_ips(self, ctx: AgentContext, region: str, result: AgentResult) -> None:
        try:
            ec2 = ctx.client("ec2", region_name=region)
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Elastic IP setup failed in {region}: {exc}")
            return

        try:
            response = ec2.describe_addresses()
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Failed to list Elastic IPs in {region}: {exc}")
            return

        for address in response.get("Addresses", []):
            if address.get("AssociationId") or address.get("InstanceId"):
                continue  # attached — not waste

            tags = {t["Key"]: t["Value"] for t in address.get("Tags", [])}
            if any(tag in ctx.request.excluded_tags for tag in tags):
                continue

            allocation_id = address.get("AllocationId", address.get("PublicIp"))
            result.findings.append(
                Finding(
                    resource_id=allocation_id,
                    finding="Unattached Elastic IP address",
                    evidence={
                        "region": region,
                        "public_ip": address.get("PublicIp"),
                        "tags": tags,
                    },
                    recommendation="Release this Elastic IP if it is no longer required.",
                    estimated_monthly_savings=ESTIMATED_ELASTIC_IP_MONTHLY_COST,
                    risk=Risk.LOW,
                    approval_required=True,
                )
            )

    # -- Data transfer (informational) ------------------------------------------------

    def _analyse_data_transfer(self, ctx: AgentContext, result: AgentResult) -> None:
        try:
            by_usage_type, total = self._get_data_transfer_cost(ctx)
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Cost Explorer data-transfer query failed: {exc}")
            return

        if total <= 0:
            return

        transfer_total = sum(by_usage_type.values())
        if total <= 0 or transfer_total / total < SIGNIFICANT_DATA_TRANSFER_SHARE:
            return

        top_usage_types = dict(
            sorted(by_usage_type.items(), key=lambda kv: kv[1], reverse=True)[:5]
        )

        result.findings.append(
            Finding(
                resource_id="data-transfer",
                finding=(
                    f"Data transfer accounts for {transfer_total / total:.0%} of total AWS "
                    f"spend over the last {ctx.request.lookback_days} days"
                ),
                evidence={
                    "monthly_cost": round(transfer_total, 2),
                    "share_of_total": round(transfer_total / total, 4),
                    "top_usage_types": {k: round(v, 2) for k, v in top_usage_types.items()},
                    "lookback_days": ctx.request.lookback_days,
                },
                recommendation=(
                    "Review cross-AZ/cross-region traffic between services (e.g. ECS/EC2 "
                    "to RDS), colocate chatty resources in the same AZ, and consider VPC "
                    "endpoints or CloudFront caching to reduce internet egress."
                ),
                estimated_monthly_savings=0.0,
                risk=Risk.LOW,
                approval_required=False,
            )
        )

    def _get_data_transfer_cost(self, ctx: AgentContext) -> tuple[dict[str, float], float]:
        ce = ctx.session.client("ce")
        end = date.today()
        start = end - timedelta(days=ctx.request.lookback_days)

        response = ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "USAGE_TYPE"}],
        )

        by_usage_type: dict[str, float] = {}
        total = 0.0
        for period in response.get("ResultsByTime", []):
            for group in period.get("Groups", []):
                usage_type = group["Keys"][0]
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                total += amount
                if any(marker in usage_type for marker in DATA_TRANSFER_USAGE_MARKERS):
                    by_usage_type[usage_type] = by_usage_type.get(usage_type, 0.0) + amount
        return by_usage_type, total

    # -- Shared helpers --------------------------------------------------------------

    @staticmethod
    def _sum_metric(
        cloudwatch, namespace: str, metric_name: str, dimension_name: str, resource_id: str, lookback_days: int
    ) -> float | None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)
        response = cloudwatch.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=[{"Name": dimension_name, "Value": resource_id}],
            StartTime=start,
            EndTime=end,
            Period=86400,
            Statistics=["Sum"],
        )
        datapoints = response.get("Datapoints", [])
        if not datapoints:
            return None
        return sum(d["Sum"] for d in datapoints)
