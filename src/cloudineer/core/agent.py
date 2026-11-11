"""Base class every Cloudineer agent implements."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from cloudineer.core.context import AgentContext
from cloudineer.core.contract import AgentResult

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Standard agent interface.

    Concrete agents implement ``name`` and ``run``. ``run`` should never raise for
    expected/partial failures (e.g. a single region's API call failing); instead
    append a message to ``AgentResult.errors`` and keep going, so one failing region
    or service doesn't take down the whole assessment.
    """

    #: Unique, stable identifier used in config (``enabled_agents``) and reports.
    name: str = "base-agent"

    @abstractmethod
    def run(self, ctx: AgentContext) -> AgentResult:
        """Execute the agent for the given context and return a standard result."""
        raise NotImplementedError

    def safe_run(self, ctx: AgentContext) -> AgentResult:
        """Run the agent, converting unexpected exceptions into an error result."""
        try:
            return self.run(ctx)
        except Exception as exc:  # noqa: BLE001 - deliberately broad: isolate agent failures
            logger.exception("Agent %s failed", self.name)
            return AgentResult(
                agent=self.name,
                account_id=ctx.request.account_id,
                errors=[f"{type(exc).__name__}: {exc}"],
            )
