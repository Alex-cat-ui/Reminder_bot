"""Shared fixtures for tests."""

import os
import pytest

# Override config to prevent sys.exit when no token
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token_123")
os.environ.setdefault("DB_PATH", ":memory:")


@pytest.fixture
def anyio_backend():
    return "asyncio"
