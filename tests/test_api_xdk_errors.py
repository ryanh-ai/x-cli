"""Tests for XDK error normalization in x_cli.api."""

from __future__ import annotations

import pytest

from x_cli.api import XApiClient


class _FakeResponse:
    def __init__(self, status_code: int, headers: dict | None = None, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeError(Exception):
    def __init__(self, response):
        super().__init__("boom")
        self.response = response


def test_xdk_429_message_contains_reset_and_remaining():
    client = XApiClient(None, None)
    err = _FakeError(_FakeResponse(429, headers={"x-rate-limit-reset": "9999999999", "x-rate-limit-remaining": "0", "x-rate-limit-limit": "180"}))

    with pytest.raises(RuntimeError, match="Rate limited") as ei:
        client._raise_xdk_error(err, "GET /2/users/:id/bookmarks")

    msg = str(ei.value)
    assert "remaining=0" in msg
    assert "reset=9999999999" in msg


def test_xdk_403_message_guides_relogin():
    client = XApiClient(None, None)
    err = _FakeError(_FakeResponse(403, payload={"errors": [{"message": "Forbidden"}]}))

    with pytest.raises(RuntimeError, match="Check OAuth2 scopes/app permissions"):
        client._raise_xdk_error(err, "GET /2/users/:id/bookmarks")


def test_require_oauth2_raises_without_manager():
    """Endpoints that require OAuth2 raise a clear error when manager is None."""
    import pytest
    from x_cli.api import XApiClient

    client = XApiClient(creds=None, oauth2=None)
    with pytest.raises(RuntimeError, match="OAuth2 user-context is not configured"):
        client._require_oauth2()


def test_get_likes_raises_without_oauth2():
    """get_likes raises RuntimeError when no OAuth2 manager is present."""
    import pytest
    from x_cli.api import XApiClient
    from unittest.mock import MagicMock

    # Provide an OAuth2 manager that reports no session
    mock_mgr = MagicMock()
    mock_mgr.has_session.return_value = False

    client = XApiClient(creds=None, oauth2=mock_mgr)
    with pytest.raises(RuntimeError, match="OAuth2 login required"):
        client.get_likes()


def test_xdk_transient_error_detection():
    """Network errors (timeout/connection) are recognised as transient."""
    from x_cli.api import XApiClient

    client = XApiClient(None, None)
    assert client._is_transient_xdk_error(Exception("connection refused"))
    assert client._is_transient_xdk_error(Exception("timeout occurred"))
    assert not client._is_transient_xdk_error(Exception("not found"))


def test_xdk_5xx_is_transient():
    """HTTP 500/502/503/504 responses from XDK are treated as transient."""
    from x_cli.api import XApiClient

    client = XApiClient(None, None)
    for status in (500, 502, 503, 504):
        err = _FakeError(_FakeResponse(status))
        assert client._is_transient_xdk_error(err), f"Expected {status} to be transient"
