"""Cost Analysis Agent — Cost Explorer trends, service breakdown and anomalies.

docs/context1.txt agent #02 / docs/architecture.md Phase 1 priority 2. Deterministic
cost-by-service breakdown is pure Boto3/Cost Explorer; the AI fallback is used only to
produce a short natural-language explanation of the single largest cost driver.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from botocore.exceptions import BotoCoreError, ClientError

from cloudineer.core.agent import BaseAgent
from cloudineer.core.context import AgentContext
from cloudineer.core.contract import AgentResult, Finding, Risk

logger = logging.getLogger(__name__)

#: Flag a service as a finding if it represents at least this share of total spend.
SIGNIFICANT_COST_SHARE = 0.10


class CostAnalysisAgent(BaseAgent):
    name = "cost-analysis"

    def run(self, ctx: AgentContext) -> AgentResult:
        result = AgentResult(agent=self.name, account_id=ctx.request.account_id)

        try:
            by_service = self._get_cost_by_service(ctx)
        except (ClientError, BotoCoreError) as exc:
            result.errors.append(f"Cost Explorer query failed: {exc}")
            return result

        total = sum(by_service.values())
        if total <= 0:
            return result

        for service, amount in sorted(by_service.items(), key=lambda kv: kv[1], reverse=True):
            share = amount / total
            if share < SIGNIFICANT_COST_SHARE:
                continue

            ai_explanation = ctx.ai.explain(
                prompt=(
                    f"In one or two sentences, explain to a FinOps stakeholder why "
                    f"'{service}' accounts for {share:.0%} (${amount:,.2f}/month) of AWS "
                    "spend and what to investigate first."
                )
            )
            if not ai_explanation:
                # Bedrock disabled/unavailable: still surface a generic, deterministic
                # recommendation so this finding always shows up under "AI Opportunities",
                # even though estimated_monthly_savings is always 0.0 for this agent.
                ai_explanation = (
                    f"'{service}' is {share:.0%} of total spend (${amount:,.2f}/month). "
                    "Review its utilisation trend and check Savings Plans/Reserved "
                    "Instance coverage for this service first."
                )

            result.findings.append(
                Finding(
                    resource_id=service,
                    finding=(
                        f"{service} represents {share:.0%} of total AWS spend over the "
                        f"last {ctx.request.lookback_days} days"
                    ),
                    evidence={
                        "monthly_cost": round(amount, 2),
                        "share_of_total": round(share, 4),
                        "lookback_days": ctx.request.lookback_days,
                    },
                    recommendation=(
                        "Review this service's resource utilisation and pricing model "
                        "with the relevant specialist agent."
                    ),
                    estimated_monthly_savings=0.0,
                    risk=Risk.LOW,
                    approval_required=False,
                    ai_explanation=ai_explanation,
                )
            )

        return result

    def _get_cost_by_service(self, ctx: AgentContext) -> dict[str, float]:
        ce = ctx.session.client("ce")  # Cost Explorer is a global/partition-level API
        end = date.today()
        start = end - timedelta(days=ctx.request.lookback_days)

        response = ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )

        totals: dict[str, float] = {}
        for period in response.get("ResultsByTime", []):
            for group in period.get("Groups", []):
                service = group["Keys"][0]
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                totals[service] = totals.get(service, 0.0) + amount
        return totals
