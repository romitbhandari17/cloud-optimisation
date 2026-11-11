"""Per-run agent context: request, AWS session(s), tools and AI fallback."""
from __future__ import annotations

from dataclasses import dataclass

import boto3

from cloudineer.core.ai.bedrock_client import AIFallback
from cloudineer.core.contract import AssessmentRequest
from cloudineer.core.tools.base import ToolRegistry


@dataclass
class AgentContext:
    """Everything an agent needs to execute a single assessment run.

    One ``AgentContext`` is built per customer run by the orchestrator and shared
    (read-only) across all enabled agents, so every agent sees the same session,
    request configuration and tool registry.
    """

    request: AssessmentRequest
    session: boto3.Session
    tools: ToolRegistry
    ai: AIFallback

    def client(self, service_name: str, *, region_name: str | None = None):
        """Convenience accessor for a boto3 client using this run's session."""
        return self.session.client(
            service_name, region_name=region_name or self.request.regions[0]
        )
