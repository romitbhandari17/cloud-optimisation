from cloudineer.core.agent import BaseAgent
from cloudineer.core.config import CustomerConfig
from cloudineer.core.context import AgentContext
from cloudineer.core.contract import AgentResult, Finding, Risk
from cloudineer.core.orchestrator import AssessmentOrchestrator
from cloudineer.core.registry import AgentRegistry
from cloudineer.reports.dashboard_builder import build_dashboard


class _FakeAgent(BaseAgent):
    name = "fake-agent"

    def run(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(
            agent=self.name,
            account_id=ctx.request.account_id,
            findings=[
                Finding(
                    resource_id="i-fake",
                    finding="Fake finding",
                    recommendation="Do something",
                    estimated_monthly_savings=42.0,
                    risk=Risk.HIGH,
                )
            ],
        )


def test_orchestrator_runs_enabled_agents_and_builds_dashboard():
    registry = AgentRegistry()
    registry.register(_FakeAgent())

    config = CustomerConfig(
        customer_id="c1",
        account_id="123456789012",
        enabled_agents=["fake-agent"],
    )

    orchestrator = AssessmentOrchestrator(registry=registry, stub_mode=True)
    results = orchestrator.run(config)

    assert len(results) == 1
    assert results[0].agent == "fake-agent"

    dashboard = build_dashboard(
        customer_id=config.customer_id, account_id=config.account_id, results=results
    )

    assert dashboard["potential_savings"]["total_monthly_usd"] == 42.0
    assert dashboard["potential_savings"]["by_agent"]["fake-agent"] == 42.0
    assert len(dashboard["priority_recommendations"]) == 1
    assert dashboard["priority_recommendations"][0]["resource_id"] == "i-fake"
