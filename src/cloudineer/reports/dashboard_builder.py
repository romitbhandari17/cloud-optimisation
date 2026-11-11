"""Assessment Dashboard builder.

Turns the standard ``AgentResult`` list produced by the orchestrator into the
dashboard shape described in docs/architecture.md §7 and requested by the product
brief: cost breakdown, potential savings, architecture risks, AI opportunities and
priority recommendations.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cloudineer.core.contract import AgentResult, Risk

_RISK_RANK = {Risk.HIGH: 0, Risk.MEDIUM: 1, Risk.LOW: 2}


def build_dashboard(
    *, customer_id: str, account_id: str, results: list[AgentResult]
) -> dict[str, Any]:
    cost_breakdown: dict[str, Any] = {}
    architecture_risks: list[dict[str, Any]] = []
    ai_opportunities: list[dict[str, Any]] = []
    savings_by_agent: dict[str, float] = {}
    all_findings: list[dict[str, Any]] = []

    for result in results:
        savings_by_agent[result.agent] = result.total_estimated_monthly_savings

        if result.agent == "cost-analysis":
            cost_breakdown = {
                f.resource_id: f.evidence.get("monthly_cost", 0.0) for f in result.findings
            }

        for finding in result.findings:
            record = {
                "agent": result.agent,
                "resource_id": finding.resource_id,
                "finding": finding.finding,
                "recommendation": finding.recommendation,
                "estimated_monthly_savings": finding.estimated_monthly_savings,
                "risk": finding.risk.value,
                "approval_required": finding.approval_required,
            }
            all_findings.append(record)

            if finding.risk in (Risk.MEDIUM, Risk.HIGH) and finding.approval_required:
                architecture_risks.append(record)

            if finding.ai_explanation:
                ai_opportunities.append(
                    {
                        "agent": result.agent,
                        "resource_id": finding.resource_id,
                        "insight": finding.ai_explanation,
                    }
                )

    priority_recommendations = sorted(
        (f for f in all_findings if f["estimated_monthly_savings"] > 0 or f["risk"] != "low"),
        key=lambda f: (_RISK_RANK[Risk(f["risk"])], -f["estimated_monthly_savings"]),
    )

    return {
        "customer_id": customer_id,
        "account_id": account_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cost_breakdown": cost_breakdown,
        "potential_savings": {
            "total_monthly_usd": round(sum(savings_by_agent.values()), 2),
            "by_agent": {k: round(v, 2) for k, v in savings_by_agent.items()},
        },
        "architecture_risks": architecture_risks,
        "ai_opportunities": ai_opportunities,
        "priority_recommendations": priority_recommendations,
        "errors": [e for r in results for e in r.errors],
    }
