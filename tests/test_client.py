"""Tests for the protocol-independent client boundary."""

import pytest

from custom_components.aqara_u200.client import PendingAqaraU200Client
from custom_components.aqara_u200.exceptions import AqaraU200BackendNotReadyError


async def test_pending_client_fails_closed() -> None:
    """Pending client must never pretend control is ready."""
    client = PendingAqaraU200Client()

    assert client.control_enabled is False

    with pytest.raises(AqaraU200BackendNotReadyError):
        await client.async_lock()

    with pytest.raises(AqaraU200BackendNotReadyError):
        await client.async_unlock()
