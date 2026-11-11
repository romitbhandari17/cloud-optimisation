"""Assessment orchestrator.

Loads customer configuration, assumes the customer's read-only role, runs every
enabled agent against a shared ``AgentContext``, and hands the results to the
dashboard builder. Agents run sequentially in this phase (easy to reason about and
test); the same ``AgentResult`` contract means this loop can later be replaced by a
Step Functions / async fan-out execution without touching agent code.
"""
from __future__ import annotations

import logging

from cloudineer.core.ai.bedrock_client import AIFallback
from cloudineer.core.config import CustomerConfig
from cloudineer.core.context import AgentContext
from cloudineer.core.contract import AgentResult
from cloudineer.core.registry import AgentRegistry, build_default_registry
from cloudineer.core.tools.aws_session import AWSSessionFactory
from cloudineer.core.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


class AssessmentOrchestrator:
    def __init__(
        self,
        *,
        registry: AgentRegistry | None = None,
        session_factory: AWSSessionFactory | None = None,
        stub_mode: bool = False,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.session_factory = session_factory or AWSSessionFactory(stub_mode=stub_mode)

    def run(self, config: CustomerConfig) -> list[AgentResult]:
        request = config.to_assessment_request()
        session = self.session_factory.get_session(
            role_arn=config.role_arn,
            external_id=config.external_id,
            session_name=f"CloudineerAssessment-{config.customer_id}",
            region_name=config.regions[0],
        )
        ctx = AgentContext(
            request=request,
            session=session,
            tools=ToolRegistry(),
            ai=AIFallback(enabled=config.ai_enabled),
        )

        agents = self.registry.resolve(config.enabled_agents)
        results: list[AgentResult] = []
        for agent in agents:
            logger.info("Running agent %s for customer %s", agent.name, config.customer_id)
            results.append(agent.safe_run(ctx))
        return results
