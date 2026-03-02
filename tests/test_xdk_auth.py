"""Tests for x_cli.xdk_auth."""

from __future__ import annotations

import json
from pathlib import Path

from x_cli.xdk_auth import OAuth2Config, OAuth2Session, XdkOAuth2Manager


def test_oauth2_session_expiry():
    s = OAuth2Session(
        access_token="a",
        refresh_token="r",
        token_type="bearer",
        scope="tweet.read",
        expires_at=0,
        obtained_at=0,
    )
    assert s.is_expired()


def test_save_load_clear_session(tmp_path: Path):
    token_file = tmp_path / "tokens.json"
    mgr = XdkOAuth2Manager(
        OAuth2Config(client_id="cid", client_secret=None, redirect_uri="http://127.0.0.1/cb", scopes=["tweet.read"]),
        token_path=token_file,
    )

    s = OAuth2Session(
        access_token="a",
        refresh_token="r",
        token_type="bearer",
        scope="tweet.read users.read",
        expires_at=9999999999,
        obtained_at=123,
    )
    mgr.save_session(s)

    assert token_file.exists()
    raw = json.loads(token_file.read_text())
    assert raw["access_token"] == "a"

    loaded = mgr.load_session()
    assert loaded is not None
    assert loaded.access_token == "a"

    mgr.clear_session()
    assert mgr.load_session() is None


def test_file_permissions_after_save(tmp_path: Path):
    """Saved token file must be chmod 600."""
    import stat

    token_file = tmp_path / "tokens.json"
    mgr = XdkOAuth2Manager(
        OAuth2Config(client_id="cid", client_secret=None, redirect_uri="http://127.0.0.1/cb", scopes=["tweet.read"]),
        token_path=token_file,
    )
    s = OAuth2Session(
        access_token="tok",
        refresh_token=None,
        token_type="bearer",
        scope="tweet.read",
        expires_at=9999999999,
        obtained_at=0,
    )
    mgr.save_session(s)
    mode = stat.S_IMODE(token_file.stat().st_mode)
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


def test_get_access_token_raises_when_expired_no_refresh_token(tmp_path: Path):
    """get_access_token must raise (not silently return expired token) when refresh_token is absent."""
    import time

    token_file = tmp_path / "tokens.json"
    mgr = XdkOAuth2Manager(
        OAuth2Config(client_id="cid", client_secret=None, redirect_uri="http://127.0.0.1/cb", scopes=["tweet.read"]),
        token_path=token_file,
    )
    expired = OAuth2Session(
        access_token="old_tok",
        refresh_token=None,  # no refresh token
        token_type="bearer",
        scope="tweet.read",
        expires_at=int(time.time()) - 3600,  # already expired
        obtained_at=0,
    )
    mgr.save_session(expired)

    import pytest
    with pytest.raises(RuntimeError, match="expired"):
        mgr.get_access_token()


def test_load_oauth2_config_requires_client_id(monkeypatch):
    """load_oauth2_config returns None when X_CLIENT_ID is absent."""
    from unittest.mock import patch
    monkeypatch.delenv("X_CLIENT_ID", raising=False)
    from x_cli.xdk_auth import load_oauth2_config
    with patch("x_cli.xdk_auth._load_dotenv_sources"):  # prevent .env reload from disk
        assert load_oauth2_config() is None


def test_load_oauth2_config_reads_client_id(monkeypatch):
    """load_oauth2_config returns a populated config when X_CLIENT_ID is set."""
    from unittest.mock import patch
    monkeypatch.setenv("X_CLIENT_ID", "my_client")
    monkeypatch.delenv("X_CLIENT_SECRET", raising=False)
    from x_cli.xdk_auth import load_oauth2_config
    with patch("x_cli.xdk_auth._load_dotenv_sources"):  # prevent .env reload from disk
        cfg = load_oauth2_config()
    assert cfg is not None
    assert cfg.client_id == "my_client"
    assert cfg.client_secret is None
