"""OAuth2 PKCE helpers backed by the official X Python XDK."""

from __future__ import annotations

import json
import os
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv


def _echo(text: str, *, err: bool = False) -> None:
    """Print via Click when available for consistent CLI routing."""
    try:
        import click  # local import to keep module lightweight outside CLI

        click.echo(text, err=err)
    except Exception:
        print(text)


DEFAULT_REDIRECT_URI = "http://127.0.0.1:3000/callback"
DEFAULT_SCOPES = [
    "tweet.read",
    "users.read",
    "bookmark.read",
    "bookmark.write",
    "like.read",
    "like.write",
    "follows.read",
    "offline.access",
]
DEFAULT_TOKEN_PATH = Path.home() / ".config" / "x-cli" / "oauth2_tokens.json"


@dataclass
class OAuth2Config:
    client_id: str
    client_secret: str | None
    redirect_uri: str
    scopes: list[str]


@dataclass
class OAuth2Session:
    access_token: str
    refresh_token: str | None
    token_type: str
    scope: str
    expires_at: int
    obtained_at: int

    @classmethod
    def from_token_response(cls, tokens: dict[str, Any]) -> "OAuth2Session":
        now = int(time.time())
        expires_in = int(tokens.get("expires_in", 7200))
        scope = tokens.get("scope", "")
        if isinstance(scope, list):
            scope = " ".join(scope)
        return cls(
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
            token_type=tokens.get("token_type", "bearer"),
            scope=scope,
            expires_at=now + max(expires_in, 1),
            obtained_at=now,
        )

    def is_expired(self, skew: int = 60) -> bool:
        return self.expires_at <= int(time.time()) + skew



def _load_dotenv_sources() -> None:
    config_env = Path.home() / ".config" / "x-cli" / ".env"
    if config_env.exists():
        load_dotenv(config_env)
    load_dotenv()


def load_oauth2_config() -> OAuth2Config | None:
    _load_dotenv_sources()
    client_id = os.environ.get("X_CLIENT_ID")
    if not client_id:
        return None

    scopes_raw = os.environ.get("X_OAUTH2_SCOPES", " ".join(DEFAULT_SCOPES)).strip()
    scopes = [s.strip() for s in scopes_raw.replace(",", " ").split() if s.strip()]

    return OAuth2Config(
        client_id=client_id,
        client_secret=os.environ.get("X_CLIENT_SECRET"),
        redirect_uri=os.environ.get("X_OAUTH2_REDIRECT_URI", DEFAULT_REDIRECT_URI),
        scopes=scopes,
    )


class XdkOAuth2Manager:
    def __init__(self, config: OAuth2Config, token_path: Path = DEFAULT_TOKEN_PATH) -> None:
        self.config = config
        self.token_path = token_path

    def load_session(self) -> OAuth2Session | None:
        if not self.token_path.exists():
            return None
        data = json.loads(self.token_path.read_text())
        return OAuth2Session(**data)

    def save_session(self, session: OAuth2Session) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.token_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(session.__dict__, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(self.token_path)

    def clear_session(self) -> None:
        if self.token_path.exists():
            self.token_path.unlink()

    def has_session(self) -> bool:
        return self.load_session() is not None

    def _new_pkce_auth(self):
        try:
            from xdk.oauth2_auth import OAuth2PKCEAuth  # type: ignore
        except Exception as e:  # pragma: no cover - depends on environment
            raise RuntimeError("xdk is not installed. Run: uv tool install .") from e

        kwargs = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": self.config.scopes,
        }
        if self.config.client_secret:
            kwargs["client_secret"] = self.config.client_secret
        return OAuth2PKCEAuth(**kwargs)

    def _can_listen_for_callback(self) -> bool:
        parsed = urlparse(self.config.redirect_uri)
        return parsed.scheme == "http" and (parsed.hostname in {"127.0.0.1", "localhost"}) and bool(parsed.port)

    def _wait_for_callback_url(self, timeout_seconds: int = 180) -> str | None:
        parsed = urlparse(self.config.redirect_uri)
        host = parsed.hostname
        port = parsed.port
        expected_path = parsed.path or "/"

        if host not in {"127.0.0.1", "localhost"} or not port:
            return None

        callback_holder: dict[str, str] = {}
        done = Event()

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                req = urlparse(self.path)
                if req.path != expected_path:
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"Not found")
                    return

                callback_holder["url"] = f"{parsed.scheme}://{host}:{port}{self.path}"
                done.set()

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>x-cli login complete</h2><p>You can close this tab and return to the terminal.</p></body></html>"
                )

            def log_message(self, format, *args):  # noqa: A003
                return

        try:
            server = HTTPServer((host, port), CallbackHandler)
        except OSError:
            return None

        server.timeout = 0.5

        def _serve_once() -> None:
            deadline = time.time() + timeout_seconds
            while not done.is_set() and time.time() < deadline:
                server.handle_request()
            server.server_close()

        t = Thread(target=_serve_once, daemon=True)
        t.start()
        t.join(timeout_seconds + 1)

        return callback_holder.get("url")

    def login_interactive(self, open_browser: bool = True) -> OAuth2Session:
        auth = self._new_pkce_auth()
        auth_url = auth.get_authorization_url()

        _echo("Open this URL and authorize x-cli:", err=True)
        _echo(auth_url)

        callback_url: str | None = None

        if self._can_listen_for_callback():
            _echo("Waiting for browser callback on local redirect URI...", err=True)
            if open_browser:
                webbrowser.open(auth_url)
            callback_url = self._wait_for_callback_url(timeout_seconds=180)
            if callback_url:
                _echo("Received callback from browser.", err=True)

        if not callback_url:
            if open_browser and not self._can_listen_for_callback():
                webbrowser.open(auth_url)
            callback_url = input("Paste the full callback URL: ").strip()

        if not callback_url:
            raise RuntimeError("No callback URL provided.")

        tokens = auth.fetch_token(authorization_response=callback_url)
        session = OAuth2Session.from_token_response(tokens)
        self.save_session(session)
        return session

    def refresh_if_needed(self, skew: int = 60) -> OAuth2Session | None:
        session = self.load_session()
        if not session:
            return None
        if not session.is_expired(skew=skew):
            return session
        if not session.refresh_token:
            return session

        auth = self._new_pkce_auth()
        refreshed: dict[str, Any] | None = None

        if hasattr(auth, "refresh_token"):
            refreshed = auth.refresh_token(refresh_token=session.refresh_token)
        elif hasattr(auth, "refresh_access_token"):
            refreshed = auth.refresh_access_token(refresh_token=session.refresh_token)

        if not refreshed:
            return session

        merged = {
            "access_token": refreshed.get("access_token", session.access_token),
            "refresh_token": refreshed.get("refresh_token", session.refresh_token),
            "token_type": refreshed.get("token_type", session.token_type),
            "scope": refreshed.get("scope", session.scope),
            "expires_in": refreshed.get("expires_in", max(1, session.expires_at - int(time.time()))),
        }
        new_session = OAuth2Session.from_token_response(merged)
        self.save_session(new_session)
        return new_session

    def get_access_token(self) -> str:
        session = self.refresh_if_needed()
        if not session:
            raise RuntimeError("OAuth2 login required. Run: x-cli auth login")
        if session.is_expired(skew=0):
            raise RuntimeError(
                "OAuth2 token has expired and cannot be refreshed (no refresh_token stored). "
                "Run: x-cli auth logout && x-cli auth login"
            )
        return session.access_token

    def logout(self) -> None:
        self.clear_session()


def load_oauth2_manager() -> XdkOAuth2Manager | None:
    cfg = load_oauth2_config()
    if not cfg:
        return None
    return XdkOAuth2Manager(cfg)
