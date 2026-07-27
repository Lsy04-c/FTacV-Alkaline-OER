"""Shared fixtures."""

from __future__ import annotations

import pytest

from oer_wf.transport import MockExecutor


@pytest.fixture
def mock_ex() -> MockExecutor:
    return MockExecutor()
