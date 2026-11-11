from typing import Any

from cloudineer.agents.network_optimisation_agent import NetworkOptimisationAgent
from cloudineer.handlers._common import run_agent_handler


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return run_agent_handler(event, agent=NetworkOptimisationAgent())
