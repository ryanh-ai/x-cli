# Code Review: OAuth2/XDK Hybrid Integration

**Reviewed:** `auth.py`, `xdk_auth.py`, `api.py`, `cli.py`, `tests/`, `README.md`, `LLMs.md`  
**Against plan:** `OAUTH2_HANDOFF.md` (XDK-first pivot from original `plan.md`)  
**Test run:** 40/40 passed (32 original + 8 new)

---

## Summary

The implementation is solid. The hybrid auth model (OAuth1 for writes, Bearer for public reads, XDK OAuth2 for self/user-context endpoints) is correctly wired. All targeted endpoints (bookmarks, likes, mentions) were migrated, `me likes` was added as a new command, and the `auth login/status/logout` group is fully functional. The XDK adapter layer in `api.py` is well-structured with proper pagination, error normalization, and model serialization.

**Verdict: Ready to merge with the fixes applied in this review.**

---

## What's Correct

- **OAuth1 signing** (`auth.py:generate_oauth_header`) — correctly includes URL query-string params in the signature base string per spec; HMAC-SHA1 with `%`-encoded key/value
- **XDK client facade** (`api.py:_xdk_client`) — cleanly resolves a fresh token per-call and constructs `xdk.Client(access_token=...)`. Lazy XDK import is correct to avoid hard dependency failure at import time
- **Atomic token write + chmod 600** (`xdk_auth.py:save_session`) — write to `.tmp`, `os.chmod(0o600)`, then `Path.replace()`. Atomic and secure
- **Browser callback server** (`xdk_auth.py:_wait_for_callback_url`) — daemon thread with Event+deadline loop, 0.5s server timeout, path validation, graceful fallback to paste when server can't bind
- **Hybrid fallback in `get_mentions()`** — OAuth2 preferred when session exists, falls back to OAuth1 without breaking existing users
- **User ID caching** (`_user_id`) — shared cache works for both auth paths since it's the same user
- **Error messages** — 429 includes reset/remaining/limit and wait_hint; 403 guides users to re-login with correct scopes; errors all use `context` string for traceability
- **`_collect_xdk_pages`** — correctly handles heterogeneous response models (dict / Pydantic / arbitrary objects), deduplicates included users by ID, caps at `max_results`
- **CLI auth group** — `auth login/status/logout` commands are clean and match plan spec
- **pyproject.toml** — `xdk>=0.4.5` added; no extraneous dependencies

---

## Fixed: Issues Resolved in This Review

### 1. `_raise_xdk_error` typed `-> None` instead of `-> NoReturn`
**File:** `api.py:74`  
**Problem:** The method always raises but was typed `-> None`. Python type checkers (mypy/pyright) correctly flag `response` as potentially unbound after the `except` block in `bookmark_tweet()` and `unbookmark_tweet()`.  
**Fix:** Changed return type to `-> NoReturn`; added `NoReturn` to `from typing import Any, NoReturn`.

### 2. Silent expired-token return in `get_access_token()`
**File:** `xdk_auth.py:refresh_if_needed` / `get_access_token`  
**Problem:** If `session.is_expired()` and `session.refresh_token is None`, `refresh_if_needed()` returns the expired session silently. `get_access_token()` then returns the expired access token. The downstream XDK API call would fail with a confusing 401.  
**Fix:** Added expiry guard in `get_access_token()`:
```python
if session.is_expired(skew=0):
    raise RuntimeError(
        "OAuth2 token has expired and cannot be refreshed (no refresh_token stored). "
        "Run: x-cli auth logout && x-cli auth login"
    )
```

### 3. `LLMs.md` project structure outdated
**File:** `LLMs.md`  
**Problem:** The `## Project Structure` code block listed only the original 3 test files; `test_xdk_auth.py` and `test_api_xdk_errors.py` were invisible to agents reading the guide.  
**Fix:** Updated structure block to include both new test files with descriptions.

### 4. Test coverage gaps vs. plan
**Files:** `tests/test_xdk_auth.py`, `tests/test_api_xdk_errors.py`  
**Problem:** The plan promised 18 new unit tests; only 4 were delivered. Missing: file permissions check, expired-no-refresh-token guard, `X_CLIENT_ID` absence/presence config tests, `_require_oauth2` without manager, `get_likes` without session, transient error detection.  
**Fix:** Added 8 targeted tests across both files. All pass.

---

## Notes (Non-Breaking Observations)

### A. `refresh_if_needed` XDK method detection is fragile
```python
if hasattr(auth, "refresh_token"):
    refreshed = auth.refresh_token(...)
elif hasattr(auth, "refresh_access_token"):
    refreshed = auth.refresh_access_token(...)
# if neither: refreshed stays None → old session returned
```
This silently falls through if XDK renames the refresh method again. The expired-token guard added in Fix 2 catches the case where refresh silently fails, so the user gets a clear error rather than a cryptic 401. The `hasattr` probing should be replaced with a try/except or a pinned XDK version contract when the XDK API stabilises.

### B. `_load_dotenv_sources()` duplicated in `auth.py` and `xdk_auth.py`
Both files have an identical private function. The clean fix (importing from `auth.py` into `xdk_auth.py`) creates a circular import because `auth.py` imports `XdkOAuth2Manager` from `xdk_auth.py`. **Resolution path:** extract `_load_dotenv_sources` into `utils.py` (no cross-imports) and import from there. Low priority; duplication is minor and stable.

### C. `_xdk_client()` not cached
Every call allocates a new `xdk.Client` and calls `oauth2.get_access_token()` (→ disk read + possible token refresh). Methods like `get_likes()` call `_oauth2_user_id()` (which calls `_xdk_client()`) then call `_xdk_client()` again — two disk reads and two client objects per API call. Consider caching the client (with token-expiry invalidation) in a future pass.

### D. `login_interactive()` uses `print()` instead of `click.echo()`
Progress messages during the login flow (`"Open this URL..."`, `"Waiting for callback..."`) use bare `print()`. These bypass Click's output routing (stdout vs stderr) and aren't suppressible. Should use `click.echo(..., err=True)` for progress and `click.echo(auth_url)` for the URL.

### E. Default redirect URI port 3000 can conflict
`DEFAULT_REDIRECT_URI = "http://127.0.0.1:3000/callback"` — port 3000 is commonly occupied by local dev servers (Next.js, Vite, Rails). The original plan specified a range of 8718-8728. Users can override via `X_OAUTH2_REDIRECT_URI`, but the troubleshooting section in README doesn't mention port conflicts. Worth adding one line there.

### F. `has_session()` does a redundant disk read
`has_session()` calls `load_session()` (disk read), and then every XDK-backed method that passes the `has_session()` gate also calls `get_access_token()` → `refresh_if_needed()` → `load_session()` (another disk read). Not a correctness issue, but a perf note for high-frequency usage.

### G. `like_tweet` / `retweet` still use OAuth1 exclusively
Per plan, this is intentional. However, if a user has OAuth2 configured but not OAuth1, these operations will fail. The README correctly documents both auth modes as additive (not exclusive), so users need both for full functionality. This should be mentioned more prominently in the "Auth" section.

### H. `plan.md` references stale architecture
`plan.md` describes `token_store.py` and `oauth2.py` as separate files, which were superseded by the XDK-first pivot documented in `OAUTH2_HANDOFF.md`. `plan.md` should either be updated to reflect the actual implementation or archived to avoid confusing future contributors.

---

## Test Coverage After This Review

| Test file | Tests | What's covered |
|-----------|-------|----------------|
| `test_auth.py` | 6 | OAuth1 header generation (all field checks + URL params) |
| `test_xdk_auth.py` | **6** (+4) | Session lifecycle, permissions, expired guard, config parsing |
| `test_api_xdk_errors.py` | **6** (+4) | 429/403 messages, `_require_oauth2`, transient detection, 5xx |
| `test_formatters.py` | 16 | All 4 output modes, verbose flag, list/dict/single variants |
| `test_utils.py` | 6 | Tweet ID parsing, @ stripping, edge cases |
| **Total** | **40** | |

### Still uncovered (future work)
- `refresh_if_needed` with a mock XDK auth object (requires `xdk` in test env)
- End-to-end `login_interactive` with a mocked callback server
- `_collect_xdk_pages` with multi-page generators
- `_model_to_dict` with Pydantic and `__dict__` fallback objects
- `post_tweet`, `delete_tweet`, `like_tweet`, `retweet` (OAuth1 write paths)
