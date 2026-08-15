"""Shared pytest configuration for Aqara U200 integration tests."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading integrations from custom_components."""
    yield
