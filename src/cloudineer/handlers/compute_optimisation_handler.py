from typing import Any

from cloudineer.agents.compute_optimisation_agent import ComputeOptimisationAgent
from cloudineer.handlers._common import run_agent_handler


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return run_agent_handler(event, agent=ComputeOptimisationAgent())
