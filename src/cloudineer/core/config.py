"""Loads per-customer YAML configuration into an ``AssessmentRequest`` + run settings."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from cloudineer.core.contract import AssessmentRequest


class CustomerConfig(BaseModel):
    """Everything about a customer that the orchestrator needs besides agent logic."""

    customer_id: str
    account_id: str
    role_arn: str | None = None
    external_id: str | None = None
    regions: list[str] = Field(default_factory=lambda: ["us-east-1"])
    environment: list[str] = Field(default_factory=lambda: ["production"])
    lookback_days: int = 30
    excluded_tags: list[str] = Field(default_factory=list)
    enabled_agents: list[str] = Field(
        default_factory=lambda: ["discovery", "cost-analysis", "compute-optimisation", "db-optimisation"]
    )
    mode: str = "assessment"
    ai_enabled: bool = True

    def to_assessment_request(self) -> AssessmentRequest:
        return AssessmentRequest(
            customer_id=self.customer_id,
            account_id=self.account_id,
            regions=self.regions,
            environment=self.environment,
            lookback_days=self.lookback_days,
            excluded_tags=self.excluded_tags,
            mode=self.mode,
        )


def load_customer_config(path: str | Path) -> CustomerConfig:
    data: dict[str, Any] = yaml.safe_load(Path(path).read_text())
    return CustomerConfig.model_validate(data)
