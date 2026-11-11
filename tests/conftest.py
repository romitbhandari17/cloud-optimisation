"""Pytest fixtures shared across tests."""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def aws_credentials():
    """Fake credentials so boto3/moto never touch real AWS during tests."""
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
