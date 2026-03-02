"""Twitter API v2 client with OAuth 1.0a, Bearer, and XDK OAuth2 user-context support."""

from __future__ import annotations

from typing import Any, NoReturn

import httpx
import time

from .auth import Credentials, generate_oauth_header
from .xdk_auth import XdkOAuth2Manager

API_BASE = "https://api.x.com/2"


class XApiClient:
    def __init__(self, creds: Credentials | None, oauth2: XdkOAuth2Manager | None = None) -> None:
        self.creds = creds
        self.oauth2 = oauth2
        self._user_id: str | None = None
        self._http = httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._http.close()

    # ---- internal ----

    def _require_creds(self) -> Credentials:
        if not self.creds:
            raise RuntimeError(
                "OAuth1/Bearer credentials are not configured. "
                "Set X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET, X_BEARER_TOKEN."
            )
        return self.creds

    def _bearer_get(self, url: str) -> dict[str, Any]:
        creds = self._require_creds()
        resp = self._http.get(url, headers={"Authorization": f"Bearer {creds.bearer_token}"})
        return self._handle(resp)

    def _oauth_request(self, method: str, url: str, json_body: dict | None = None) -> dict[str, Any]:
        creds = self._require_creds()
        auth_header = generate_oauth_header(method, url, creds)
        headers: dict[str, str] = {"Authorization": auth_header}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        resp = self._http.request(method, url, headers=headers, json=json_body if json_body else None)
        return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 429:
            reset = resp.headers.get("x-rate-limit-reset", "unknown")
            raise RuntimeError(f"Rate limited. Resets at {reset}.")

        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        if not resp.is_success:
            errors = data.get("errors", []) if isinstance(data, dict) else []
            msg = "; ".join(e.get("detail") or e.get("message", "") for e in errors) or resp.text[:500]
            raise RuntimeError(f"API error (HTTP {resp.status_code}): {msg}")
        return data if isinstance(data, dict) else {"data": data}

    def _is_transient_xdk_error(self, err: Exception) -> bool:
        resp = getattr(err, "response", None)
        if resp is None:
            text = str(err).lower()
            return "timeout" in text or "tempor" in text or "connection" in text
        status = getattr(resp, "status_code", 0) or 0
        return status in (500, 502, 503, 504)

    def _raise_xdk_error(self, err: Exception, context: str) -> NoReturn:
        resp = getattr(err, "response", None)
        if resp is None:
            raise RuntimeError(f"{context} failed: {err}") from err

        status = getattr(resp, "status_code", None)
        headers = getattr(resp, "headers", {}) or {}

        detail = ""
        try:
            payload = resp.json()
            errors = payload.get("errors", []) if isinstance(payload, dict) else []
            detail = "; ".join(e.get("detail") or e.get("message", "") for e in errors if isinstance(e, dict))
        except Exception:
            detail = (getattr(resp, "text", "") or "")[:300]

        if status == 429:
            reset = headers.get("x-rate-limit-reset", "unknown")
            remaining = headers.get("x-rate-limit-remaining", "?")
            limit = headers.get("x-rate-limit-limit", "?")
            wait_hint = ""
            try:
                wait_seconds = max(0, int(reset) - int(time.time()))
                wait_hint = f" (~{wait_seconds}s)"
            except Exception:
                pass
            raise RuntimeError(
                f"Rate limited on {context} (HTTP 429). "
                f"limit={limit} remaining={remaining} reset={reset}{wait_hint}."
            ) from err

        if status == 403:
            msg = detail or "Forbidden"
            raise RuntimeError(
                f"Access denied on {context} (HTTP 403): {msg}. "
                "Check OAuth2 scopes/app permissions, then run: x-cli auth logout && x-cli auth login"
            ) from err

        msg = detail or (getattr(resp, "text", "") or "").strip()[:300] or "Unknown error"
        raise RuntimeError(f"XDK API error on {context} (HTTP {status}): {msg}") from err

    def _require_oauth2(self) -> XdkOAuth2Manager:
        if not self.oauth2:
            raise RuntimeError(
                "OAuth2 user-context is not configured. "
                "Set X_CLIENT_ID (and optional X_CLIENT_SECRET), then run: x-cli auth login"
            )
        return self.oauth2

    def _xdk_client(self):
        oauth2 = self._require_oauth2()
        token = oauth2.get_access_token()
        try:
            from xdk import Client  # type: ignore
        except Exception as e:  # pragma: no cover - environment dependent
            raise RuntimeError("xdk is not installed. Run: uv tool install .") from e
        return Client(access_token=token)

    @staticmethod
    def _model_to_dict(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return [XApiClient._model_to_dict(v) for v in value]
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "dict"):
            return value.dict()
        if hasattr(value, "__dict__"):
            return {k: XApiClient._model_to_dict(v) for k, v in value.__dict__.items() if not k.startswith("_")}
        return value

    @classmethod
    def _response_to_dict(cls, response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response

        data = cls._model_to_dict(getattr(response, "data", None))
        includes_raw = cls._model_to_dict(getattr(response, "includes", None)) or {}
        meta = cls._model_to_dict(getattr(response, "meta", None)) or {}

        out: dict[str, Any] = {}
        if data is not None:
            out["data"] = data
        if includes_raw:
            out["includes"] = includes_raw
        if meta:
            out["meta"] = meta
        if not out:
            out = cls._model_to_dict(response) or {}
        return out

    def _collect_xdk_pages(self, pages: Any, max_results: int, context: str = "XDK paginated request") -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        users: list[dict[str, Any]] = []
        next_token: str | None = None

        try:
            for page in pages:
                page_dict = self._response_to_dict(page)
                page_data = page_dict.get("data", []) or []
                if isinstance(page_data, dict):
                    page_data = [page_data]
                items.extend(page_data)

                inc = page_dict.get("includes", {}) or {}
                inc_users = inc.get("users", []) if isinstance(inc, dict) else []
                if inc_users:
                    users.extend(inc_users)

                meta = page_dict.get("meta", {}) or {}
                if isinstance(meta, dict) and meta.get("next_token"):
                    next_token = meta["next_token"]

                if len(items) >= max_results:
                    break
        except Exception as e:
            self._raise_xdk_error(e, context)

        result: dict[str, Any] = {"data": items[:max_results]}
        if users:
            uniq: dict[str, dict[str, Any]] = {}
            for u in users:
                uid = u.get("id") if isinstance(u, dict) else None
                if uid:
                    uniq[uid] = u
            result["includes"] = {"users": list(uniq.values())}

        meta_out: dict[str, Any] = {"result_count": len(result["data"])}
        if next_token:
            meta_out["next_token"] = next_token
        result["meta"] = meta_out
        return result

    def _oauth2_user_id(self) -> str:
        if self._user_id:
            return self._user_id
        client = self._xdk_client()

        me = None
        for attempt in range(3):
            try:
                me = client.users.get_me(user_fields=["id", "username", "name"])  # type: ignore[attr-defined]
                break
            except Exception as e:
                if self._is_transient_xdk_error(e) and attempt < 2:
                    time.sleep(1.5 * (2**attempt))
                    continue
                self._raise_xdk_error(e, "GET /2/users/me")

        me_dict = self._response_to_dict(me)
        data = me_dict.get("data", {})
        uid = data.get("id") if isinstance(data, dict) else None
        if not uid:
            raise RuntimeError("Failed to resolve authenticated user ID via OAuth2")
        self._user_id = uid
        return uid

    # ---- users/self ----

    def get_authenticated_user_id(self) -> str:
        if self.oauth2 and self.oauth2.has_session():
            return self._oauth2_user_id()
        if self._user_id:
            return self._user_id
        data = self._oauth_request("GET", f"{API_BASE}/users/me")
        self._user_id = data["data"]["id"]
        return self._user_id

    # ---- tweets ----

    def post_tweet(
        self,
        text: str,
        reply_to: str | None = None,
        quote_tweet_id: str | None = None,
        poll_options: list[str] | None = None,
        poll_duration_minutes: int = 1440,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        if quote_tweet_id:
            body["quote_tweet_id"] = quote_tweet_id
        if poll_options:
            body["poll"] = {"options": poll_options, "duration_minutes": poll_duration_minutes}
        return self._oauth_request("POST", f"{API_BASE}/tweets", body)

    def delete_tweet(self, tweet_id: str) -> dict[str, Any]:
        return self._oauth_request("DELETE", f"{API_BASE}/tweets/{tweet_id}")

    def get_tweet(self, tweet_id: str) -> dict[str, Any]:
        params = {
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,in_reply_to_user_id,referenced_tweets,attachments,entities,lang,note_tweet",
            "expansions": "author_id,referenced_tweets.id,attachments.media_keys",
            "user.fields": "name,username,verified,profile_image_url,public_metrics",
            "media.fields": "url,preview_image_url,type,width,height,alt_text",
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return self._bearer_get(f"{API_BASE}/tweets/{tweet_id}?{qs}")

    def search_tweets(self, query: str, max_results: int = 10) -> dict[str, Any]:
        creds = self._require_creds()
        max_results = max(10, min(max_results, 100))
        params = {
            "query": query,
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "name,username,verified,profile_image_url",
            "media.fields": "url,preview_image_url,type",
        }
        url = f"{API_BASE}/tweets/search/recent"
        resp = self._http.get(url, params=params, headers={"Authorization": f"Bearer {creds.bearer_token}"})
        return self._handle(resp)

    def get_tweet_metrics(self, tweet_id: str) -> dict[str, Any]:
        params = "tweet.fields=public_metrics,non_public_metrics,organic_metrics"
        return self._oauth_request("GET", f"{API_BASE}/tweets/{tweet_id}?{params}")

    # ---- users ----

    def get_user(self, username: str) -> dict[str, Any]:
        fields = "user.fields=created_at,description,public_metrics,verified,profile_image_url,url,location,pinned_tweet_id"
        return self._bearer_get(f"{API_BASE}/users/by/username/{username}?{fields}")

    def get_timeline(self, user_id: str, max_results: int = 10) -> dict[str, Any]:
        creds = self._require_creds()
        max_results = max(5, min(max_results, 100))
        params = {
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions": "author_id,attachments.media_keys,referenced_tweets.id",
            "user.fields": "name,username,verified",
            "media.fields": "url,preview_image_url,type",
        }
        resp = self._http.get(
            f"{API_BASE}/users/{user_id}/tweets",
            params=params,
            headers={"Authorization": f"Bearer {creds.bearer_token}"},
        )
        return self._handle(resp)

    def get_followers(self, user_id: str, max_results: int = 100) -> dict[str, Any]:
        creds = self._require_creds()
        max_results = max(1, min(max_results, 1000))
        params = {
            "max_results": str(max_results),
            "user.fields": "created_at,description,public_metrics,verified,profile_image_url",
        }
        resp = self._http.get(
            f"{API_BASE}/users/{user_id}/followers",
            params=params,
            headers={"Authorization": f"Bearer {creds.bearer_token}"},
        )
        return self._handle(resp)

    def get_following(self, user_id: str, max_results: int = 100) -> dict[str, Any]:
        creds = self._require_creds()
        max_results = max(1, min(max_results, 1000))
        params = {
            "max_results": str(max_results),
            "user.fields": "created_at,description,public_metrics,verified,profile_image_url",
        }
        resp = self._http.get(
            f"{API_BASE}/users/{user_id}/following",
            params=params,
            headers={"Authorization": f"Bearer {creds.bearer_token}"},
        )
        return self._handle(resp)

    def get_mentions(self, max_results: int = 10) -> dict[str, Any]:
        # Prefer OAuth2 (XDK) when available, fallback to OAuth1 for compatibility.
        if self.oauth2 and self.oauth2.has_session():
            user_id = self._oauth2_user_id()
            client = self._xdk_client()
            pages = client.users.get_mentions(  # type: ignore[attr-defined]
                user_id,
                max_results=max(5, min(max_results, 100)),
                tweet_fields=["created_at", "public_metrics", "author_id", "conversation_id", "entities", "note_tweet"],
                expansions=["author_id"],
                user_fields=["name", "username", "verified"],
            )
            return self._collect_xdk_pages(pages, max_results, context="GET /2/users/:id/mentions")

        user_id = self.get_authenticated_user_id()
        max_results = max(5, min(max_results, 100))
        params = {
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,note_tweet",
            "expansions": "author_id",
            "user.fields": "name,username,verified",
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{API_BASE}/users/{user_id}/mentions?{qs}"
        return self._oauth_request("GET", url)

    # ---- engagement ----

    def like_tweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        return self._oauth_request("POST", f"{API_BASE}/users/{user_id}/likes", {"tweet_id": tweet_id})

    def retweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        return self._oauth_request("POST", f"{API_BASE}/users/{user_id}/retweets", {"tweet_id": tweet_id})

    def get_likes(self, max_results: int = 10) -> dict[str, Any]:
        oauth2 = self._require_oauth2()
        if not oauth2.has_session():
            raise RuntimeError("OAuth2 login required. Run: x-cli auth login")

        user_id = self._oauth2_user_id()
        client = self._xdk_client()
        pages = client.users.get_liked_posts(  # type: ignore[attr-defined]
            user_id,
            max_results=max(1, min(max_results, 100)),
            tweet_fields=["created_at", "public_metrics", "author_id", "conversation_id", "entities", "lang", "note_tweet"],
            expansions=["author_id"],
            user_fields=["name", "username", "verified", "profile_image_url"],
        )
        return self._collect_xdk_pages(pages, max_results, context="GET /2/users/:id/liked_tweets")

    # ---- bookmarks ----

    def get_bookmarks(self, max_results: int = 10) -> dict[str, Any]:
        oauth2 = self._require_oauth2()
        if not oauth2.has_session():
            raise RuntimeError("OAuth2 login required. Run: x-cli auth login")

        user_id = self._oauth2_user_id()
        client = self._xdk_client()
        pages = client.users.get_bookmarks(  # type: ignore[attr-defined]
            user_id,
            max_results=max(1, min(max_results, 100)),
            tweet_fields=["created_at", "public_metrics", "author_id", "conversation_id", "entities", "lang", "note_tweet"],
            expansions=["author_id", "attachments.media_keys"],
            user_fields=["name", "username", "verified", "profile_image_url"],
            media_fields=["url", "preview_image_url", "type"],
        )
        return self._collect_xdk_pages(pages, max_results, context="GET /2/users/:id/bookmarks")

    def bookmark_tweet(self, tweet_id: str) -> dict[str, Any]:
        oauth2 = self._require_oauth2()
        if not oauth2.has_session():
            raise RuntimeError("OAuth2 login required. Run: x-cli auth login")

        user_id = self._oauth2_user_id()
        client = self._xdk_client()
        try:
            response = client.users.create_bookmark(user_id, body={"tweet_id": tweet_id})  # type: ignore[attr-defined]
        except Exception as e:
            self._raise_xdk_error(e, "POST /2/users/:id/bookmarks")
        return self._response_to_dict(response)

    def unbookmark_tweet(self, tweet_id: str) -> dict[str, Any]:
        oauth2 = self._require_oauth2()
        if not oauth2.has_session():
            raise RuntimeError("OAuth2 login required. Run: x-cli auth login")

        user_id = self._oauth2_user_id()
        client = self._xdk_client()
        try:
            response = client.users.delete_bookmark(user_id, tweet_id)  # type: ignore[attr-defined]
        except Exception as e:
            self._raise_xdk_error(e, "DELETE /2/users/:id/bookmarks/:tweet_id")
        return self._response_to_dict(response)
