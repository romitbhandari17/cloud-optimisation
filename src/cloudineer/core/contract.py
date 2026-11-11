"""Standard agent input/output contract.

Every agent in the Cloudineer FinOps Agent Library accepts an ``AssessmentRequest``
and returns an ``AgentResult``. This standardisation (see docs/architecture.md §3/§6
and docs/context1.txt §4) is what makes agents reusable, testable and composable by
the orchestrator and dashboard without any agent-specific glue code.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Mode(str, Enum):
    ASSESSMENT = "assessment"
    REMEDIATION = "remediation"


class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AssessmentRequest(BaseModel):
    """Standard input configuration shared by every agent."""

    customer_id: str
    account_id: str
    regions: list[str] = Field(default_factory=lambda: ["us-east-1"])
    environment: list[str] = Field(default_factory=lambda: ["production"])
    lookback_days: int = 30
    excluded_tags: list[str] = Field(default_factory=list)
    mode: Mode = Mode.ASSESSMENT


class Finding(BaseModel):
    """A single, actionable observation produced by an agent."""

    resource_id: str
    finding: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    recommendation: str
    estimated_monthly_savings: float = 0.0
    currency: str = "USD"
    risk: Risk = Risk.MEDIUM
    approval_required: bool = True
    ai_explanation: str | None = None


class AgentResult(BaseModel):
    """Standard output every agent returns."""

    agent: str
    account_id: str
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    findings: list[Finding] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @property
    def total_estimated_monthly_savings(self) -> float:
        return sum(f.estimated_monthly_savings for f in self.findings)
