from typing import Any

from cloudineer.agents.discovery_agent import DiscoveryAgent
from cloudineer.handlers._common import run_agent_handler


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return run_agent_handler(event, agent=DiscoveryAgent())
