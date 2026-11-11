"""Lambda entry points — one per agent, invoked by the Step Functions state machine.

Each handler:
  1. Validates the incoming event into a ``CustomerConfig``.
  2. Assumes the customer's cross-account read-only role via STS
     (``core/tools/aws_session.py``).
  3. Builds the shared ``AgentContext`` and runs exactly one agent via
     ``BaseAgent.safe_run`` (never raises — failures become ``AgentResult.errors``).
  4. Returns the agent's ``AgentResult`` as plain JSON for Step Functions to pass on.

Keeping one Lambda per agent (rather than one Lambda for everything) means a new
agent only needs a new handler + a new Step Functions branch — the core framework
and every existing agent/handler are untouched.
"""
from __future__ import annotations

import logging
from typing import Any

from cloudineer.core.agent import BaseAgent
from cloudineer.core.ai.bedrock_client import AIFallback
from cloudineer.core.config import CustomerConfig
from cloudineer.core.context import AgentContext
from cloudineer.core.contract import AgentResult
from cloudineer.core.tools.aws_session import AWSSessionFactory
from cloudineer.core.tools.base import ToolRegistry

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_session_factory = AWSSessionFactory()


def build_context(event: dict[str, Any]) -> tuple[CustomerConfig, AgentContext]:
    """Shared event -> (CustomerConfig, AgentContext) step used by every handler.

    Expected event shape (this is exactly what the Step Functions state machine
    passes to each agent Lambda — see terraform/compute/statemachine/assessment.asl.json):

        {"customer_config": {...same shape as config/customers/<id>.yaml...}}
    """
    config = CustomerConfig.model_validate(event["customer_config"])
    request = config.to_assessment_request()

    session = _session_factory.get_session(
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
    return config, ctx


def run_agent_handler(event: dict[str, Any], *, agent: BaseAgent) -> dict[str, Any]:
    """Shared body for every per-agent Lambda handler.

    Any failure — including an invalid event payload or a failed cross-account
    ``AssumeRole`` — is converted into a standard ``AgentResult`` with ``errors``
    populated, rather than raising. This keeps the Step Functions state machine
    simple (no branch-specific ``Catch`` wiring needed): a failed agent still
    produces a well-formed result the dashboard builder can aggregate.
    """
    account_id = event.get("customer_config", {}).get("account_id", "unknown")
    try:
        _, ctx = build_context(event)
    except Exception as exc:  # noqa: BLE001 - isolate handler-level setup failures
        logger.exception("Failed to build agent context for %s", agent.name)
        return AgentResult(
            agent=agent.name,
            account_id=account_id,
            errors=[f"{type(exc).__name__}: {exc}"],
        ).model_dump(mode="json")

    return agent.safe_run(ctx).model_dump(mode="json")
