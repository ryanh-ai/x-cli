# x-cli OAuth2 Plan (Updated): XDK-First Hybrid Migration

## Decision Update
After checking official X docs + samples, the recommended approach is now:

**Use official Python XDK (`xdk`) as the auth/API engine for user-context flows**, while preserving current `x-cli` command UX and formatters.

Why:
- Officially supports OAuth2 PKCE + OAuth1 + bearer
- Official samples exist for your exact targets (bookmarks, likes, mentions)
- Less custom auth maintenance risk than hand-rolled PKCE/token lifecycle

---

## Evidence used
- `docs.x.com/xdks/python/overview` (official Python XDK, OpenAPI-generated, OAuth2 PKCE support)
- `docs.x.com/x-api/tools-and-libraries/sdks` (official SDK auth examples)
- `xdevplatform/samples` Python examples:
  - `python/users/bookmark/get_bookmarks.py`
  - `python/users/like/get_liked_posts.py`
  - `python/users/timeline/get_mentions.py`

---

## Scope of this migration

### Keep as-is (initially)
- CLI structure/commands in `src/x_cli/cli.py`
- Output modes in `src/x_cli/formatters.py`
- Existing OAuth1 signer in `src/x_cli/auth.py`
- Existing endpoints already working with bearer/OAuth1

### Migrate first (priority)
- `me bookmarks`
- `me bookmark`
- `me unbookmark`
- `me mentions`
- `me likes` (new)

These should use XDK + OAuth2 user context.

---

## Architecture target

Introduce an adapter layer so CLI doesn’t care whether backend is legacy httpx or XDK.

- `XApiClient` remains the facade used by `cli.py`
- Internally:
  - Legacy code path for existing bearer/OAuth1 endpoints
  - New XDK-backed path for OAuth2-required user-context endpoints
- Add auth commands:
  - `x-cli auth login`
  - `x-cli auth status`
  - `x-cli auth logout`

---

## File-level plan

## 1) `pyproject.toml`
Add dependency:
- `xdk>=0.4.5`

## 2) New `src/x_cli/xdk_auth.py`
Purpose: wrap XDK OAuth2 PKCE flow + token persistence.

Implement:
- `OAuth2Config` dataclass (`client_id`, `client_secret`, `redirect_uri`, `scopes`)
- `OAuth2Session` dataclass (`access_token`, `refresh_token`, `expires_at`, `scope`, `token_type`)
- `load_oauth2_config_from_env()`
- `load_session()` / `save_session()` / `clear_session()`
- `login_interactive()`:
  - construct `OAuth2PKCEAuth`
  - print/open authorization URL
  - accept callback URL paste (Phase 1)
  - exchange code -> tokens -> persist
- `refresh_if_needed()`

Token file:
- `~/.config/x-cli/oauth2_tokens.json`
- atomic write + chmod 600

## 3) Update `src/x_cli/auth.py`
Keep current OAuth1 functions unchanged for compatibility.
Add helper:
- `load_auth_context()` returns available OAuth1 creds + OAuth2 config/session (if present)

## 4) Update `src/x_cli/api.py`
Add XDK-backed methods for user-context endpoints:
- `get_mentions()` -> XDK `client.users.get_mentions(...)`
- `get_bookmarks()` -> XDK `client.users.get_bookmarks(...)`
- `bookmark_tweet()` / `unbookmark_tweet()` -> XDK user bookmark ops
- `get_likes()` (new) -> XDK `client.users.get_liked_posts(...)`

Implementation notes:
- Build XDK client from current OAuth2 access token
- Resolve `me` user id once via XDK `client.users.get_me()` and cache it
- Convert/normalize XDK response models to dict shape expected by existing formatters
- If no valid OAuth2 session:
  - raise actionable error: `OAuth2 login required. Run: x-cli auth login`
- On 401:
  - attempt refresh once, retry once

## 5) Update `src/x_cli/cli.py`
Add group:
- `auth login`
- `auth status`
- `auth logout`

Add command:
- `me likes --max N`

No output format changes required.

## 6) Tests
Add:
- `tests/test_xdk_auth.py`
- `tests/test_api_oauth2_xdk.py`

Cases:
1. Missing `X_CLIENT_ID` gives clear login/setup error
2. Session save/load permissions
3. Expired token triggers refresh path
4. OAuth2-required endpoint without session errors correctly
5. `me likes` wiring
6. Existing OAuth1 tests still pass unchanged

(Use mocking for XDK classes, no live API in CI.)

## 7) Docs
Update `README.md` and `LLMs.md`:
- Official XDK-backed OAuth2 mode
- Required env:
  - `X_CLIENT_ID`
  - optional `X_CLIENT_SECRET`
  - optional `X_OAUTH2_REDIRECT_URI`
- New commands (`auth login/status/logout`, `me likes`)
- Troubleshooting for scope/auth mismatch

---

## Endpoint/auth matrix (updated)

- Keep bearer: tweet/user public reads
- Keep OAuth1: post/delete/retweet/like (for now)
- Move to OAuth2 via XDK:
  - `me mentions`
  - `me bookmarks`
  - `me bookmark`
  - `me unbookmark`
  - `me likes`

---

## Migration strategy

## Phase 1 (recommended now)
Hybrid mode:
- Introduce XDK only for OAuth2-required self endpoints
- Preserve all existing command behavior
- Lowest-risk path to unblock your authenticated usage

## Phase 2 (optional)
Move additional endpoints to XDK for consistency and reduce direct HTTP code.

---

## Risks and mitigations

1. **XDK response model differences**
   - Mitigation: adapter functions in `api.py` to normalize to dict
2. **Token refresh/storage assumptions**
   - Mitigation: keep token schema explicit and versioned in JSON
3. **SDK changes upstream**
   - Mitigation: pin minimum version; add thin compatibility wrapper in `xdk_auth.py`

Rollback:
- Keep legacy methods intact; if needed, disable XDK paths with env flag `X_CLI_USE_XDK_OAUTH2=0`

---

## Implementation checklist

1. [ ] Add `xdk` dependency
2. [ ] Add `xdk_auth.py` (config/session/login/refresh)
3. [ ] Add `auth` CLI commands
4. [ ] Add XDK-backed methods for mentions/bookmarks/likes
5. [ ] Add `me likes`
6. [ ] Add tests (mocked XDK)
7. [ ] Update docs
8. [ ] Manual smoke test with your app creds

Estimated effort: **4–6 hours**

---

## Immediate next commands

```bash
cd x-cli
git checkout -b feat/xdk-oauth2-hybrid
```

Then implement in this order: dependency -> `xdk_auth.py` -> auth CLI -> API adapter methods -> tests -> docs.
