"""Registry mapping agent name -> agent class/instance.

Lets customer configuration enable/disable agents by name (``enabled_agents`` in
``config/customers/<id>.yaml``) without any code changes, per docs/architecture.md §6.
"""
from __future__ import annotations

from cloudineer.core.agent import BaseAgent


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        if agent.name in self._agents:
            raise ValueError(f"Agent {agent.name!r} is already registered")
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise KeyError(
                f"Unknown agent {name!r}. Registered: {sorted(self._agents)}"
            ) from exc

    def resolve(self, names: list[str]) -> list[BaseAgent]:
        return [self.get(name) for name in names]

    def names(self) -> list[str]:
        return sorted(self._agents)


def build_default_registry() -> AgentRegistry:
    """Registers the Phase 1 agents (docs/architecture.md §2)."""
    from cloudineer.agents.compute_optimisation_agent import ComputeOptimisationAgent
    from cloudineer.agents.cost_analysis_agent import CostAnalysisAgent
    from cloudineer.agents.db_optimisation_agent import DatabaseOptimisationAgent
    from cloudineer.agents.discovery_agent import DiscoveryAgent
    from cloudineer.agents.network_optimisation_agent import NetworkOptimisationAgent

    registry = AgentRegistry()
    registry.register(DiscoveryAgent())
    registry.register(CostAnalysisAgent())
    registry.register(ComputeOptimisationAgent())
    registry.register(DatabaseOptimisationAgent())
    registry.register(NetworkOptimisationAgent())
    return registry
