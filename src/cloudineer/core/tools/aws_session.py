"""Cross-account AWS session management.

Implements the central-control-plane + customer-execution model from
docs/context2.txt §2: Cloudineer assumes a narrowly-scoped, read-only IAM role in the
customer's account via STS, and agents use the resulting temporary credentials. No
long-lived customer credentials are ever stored.
"""
from __future__ import annotations

import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

#: Session duration for assessment-only, read-only work. Kept short deliberately.
DEFAULT_SESSION_DURATION_SECONDS = 3600


class AssumeRoleError(RuntimeError):
    """Raised when Cloudineer cannot assume the customer's assessment role."""


class AWSSessionFactory:
    """Builds a boto3 Session scoped to a single customer account.

    In ``stub_mode`` (no ``role_arn`` configured, or explicitly requested) this
    returns the default local/dev session instead of assuming a role, so the
    framework and agents can be developed and unit tested without live AWS access.
    """

    def __init__(self, *, stub_mode: bool = False) -> None:
        self._stub_mode = stub_mode
        self._sts_client = None

    @property
    def sts_client(self):
        if self._sts_client is None:
            self._sts_client = boto3.client("sts")
        return self._sts_client

    def get_session(
        self,
        *,
        role_arn: str | None,
        external_id: str | None = None,
        session_name: str = "CloudineerAssessment",
        region_name: str | None = None,
    ) -> boto3.Session:
        if self._stub_mode or not role_arn:
            logger.info("AWSSessionFactory: using local/default credentials (stub mode)")
            return boto3.Session(region_name=region_name)

        assume_role_kwargs: dict = {
            "RoleArn": role_arn,
            "RoleSessionName": session_name,
            "DurationSeconds": DEFAULT_SESSION_DURATION_SECONDS,
        }
        if external_id:
            assume_role_kwargs["ExternalId"] = external_id

        try:
            response = self.sts_client.assume_role(**assume_role_kwargs)
        except (ClientError, BotoCoreError) as exc:
            raise AssumeRoleError(
                f"Unable to assume role {role_arn!r}: {exc}"
            ) from exc

        creds = response["Credentials"]
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region_name,
        )
