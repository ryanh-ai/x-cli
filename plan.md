Plan written to `/Users/rhoium/Projects/code-agent-playground/pi/x-cli/plan.md`.

## Summary of what the plan covers:

**Codebase review**: Full audit of all 6 source files and 3 test files — mapped every endpoint to its current auth method and required OAuth2 scopes (16 endpoints total).

**Option analysis**: Evaluated 3 approaches (OAuth2-only, OAuth2 alongside OAuth1 with auto-detect, OAuth2 via flag). **Recommended Option B**: auto-detect with OAuth2 preferred → OAuth1 fallback → error. Zero breaking changes.

**File changes (7 tasks)**:
1. **New `token_store.py`** — `OAuth2Tokens` dataclass + atomic JSON persistence at `~/.config/x-cli/tokens.json` with `0o600` perms
2. **New `oauth2.py`** — Full PKCE flow: code verifier/challenge generation, localhost callback server (port range 8718-8728), token exchange, refresh, revoke
3. **Updated `auth.py`** — New `load_auth()` returns `(OAuth2Tokens|None, Credentials|None)`, keeps existing functions unchanged
4. **Updated `api.py`** — New `_authed_request()` with proactive refresh + 401 retry + OAuth1 fallback. All 16 endpoint methods updated to use unified dispatcher
5. **Updated `cli.py`** — New `auth` command group (`login`, `status`, `logout`). `State.client` uses `load_auth()`
6. **New tests** — 18 new unit tests across `test_token_store.py` and `test_oauth2.py`
7. **Docs** — README, LLMs.md, .gitignore updates

**Zero new dependencies** — everything uses stdlib + existing httpx.

**Total estimate**: ~5 hours.