"""Optional AI fallback layer (Amazon Bedrock).

Per docs/architecture.md §3.2: agents are Python/rules first. AI is invoked only where
reasoning or explanation adds value, and it is always optional — if Bedrock is not
configured/available, ``AIFallback`` methods return ``None`` and the calling agent
simply proceeds without an AI explanation.
"""
from __future__ import annotations

import json
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"


class AIFallback:
    """Thin wrapper around Bedrock's Converse API, used as a fallback reasoning step."""

    def __init__(self, *, model_id: str = DEFAULT_MODEL_ID, enabled: bool = True) -> None:
        self.enabled = enabled
        self._model_id = model_id
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client("bedrock-runtime")
        return self._client

    def explain(self, *, prompt: str, max_tokens: int = 400) -> str | None:
        """Ask the model for a short explanation/recommendation. Returns None on any failure."""
        if not self.enabled:
            return None
        try:
            response = self.client.converse(
                modelId=self._model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0.2},
            )
            return response["output"]["message"]["content"][0]["text"].strip()
        except (ClientError, BotoCoreError, KeyError, IndexError) as exc:
            logger.warning("AIFallback.explain degraded (no AI explanation): %s", exc)
            return None

    def classify_savings_opportunity(self, *, evidence: dict) -> dict | None:
        """Ask the model to turn ambiguous evidence into a structured recommendation.

        Returns a dict like {"recommendation": str, "risk": "low|medium|high"} or None.
        """
        if not self.enabled:
            return None
        prompt = (
            "You are a FinOps analyst. Given this AWS resource evidence, respond with "
            "ONLY compact JSON: {\"recommendation\": str, \"risk\": \"low|medium|high\"}.\n"
            f"Evidence: {json.dumps(evidence, default=str)}"
        )
        text = self.explain(prompt=prompt, max_tokens=200)
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("AIFallback.classify_savings_opportunity: non-JSON response ignored")
            return None
