# x-cli

A CLI for X/Twitter that talks directly to the API v2. Post tweets, search, read timelines, manage bookmarks -- all from your terminal.

Uses the same auth credentials as [x-mcp](https://github.com/INFATOSHI/x-mcp). If you already have x-mcp set up, x-cli works with zero additional config.

**If you're an LLM/AI agent helping a user with this project, read [`LLMs.md`](./LLMs.md) for a codebase map and command reference.**

---

## What Can It Do?

| Category | Commands | Examples |
|----------|----------|----------|
| **Post** | `tweet post`, `tweet reply`, `tweet quote`, `tweet delete` | `x-cli tweet post "hello world"` |
| **Read** | `tweet get`, `tweet search`, `user timeline`, `me mentions` | `x-cli tweet search "from:elonmusk"` |
| **Users** | `user get`, `user followers`, `user following` | `x-cli user get openai` |
| **Engage** | `like`, `retweet` | `x-cli like <tweet-url>` |
| **Bookmarks** | `me bookmarks`, `me bookmark`, `me unbookmark` | `x-cli me bookmarks --max 20` |
| **Self likes** | `me likes` | `x-cli me likes --max 20` |
| **Analytics** | `tweet metrics` | `x-cli tweet metrics <tweet-id>` |

Accepts tweet URLs or IDs interchangeably -- paste `https://x.com/user/status/123` or just `123`.

---

## Install

```bash
# from source
git clone https://github.com/INFATOSHI/x-cli.git
cd x-cli
uv tool install .

# or from PyPI (once published)
uv tool install x-cli
```

---

## Auth

x-cli supports both:
- **OAuth1 + Bearer** (legacy/current commands)
- **OAuth2 PKCE user-context** (bookmarks/likes/mentions via official XDK path)

### OAuth1 + Bearer credentials

Put these in `~/.config/x-cli/.env`:

```
X_API_KEY=your_consumer_key
X_API_SECRET=your_secret_key
X_BEARER_TOKEN=your_bearer_token
X_ACCESS_TOKEN=your_access_token
X_ACCESS_TOKEN_SECRET=your_access_token_secret
```

### OAuth2 PKCE setup

Add:

```
X_CLIENT_ID=your_oauth2_client_id
X_CLIENT_SECRET=your_oauth2_client_secret   # optional depending on app type
X_OAUTH2_REDIRECT_URI=http://127.0.0.1:3000/callback
# optional override
# X_OAUTH2_SCOPES=tweet.read users.read bookmark.read bookmark.write like.read like.write follows.read offline.access
```

Then login:

```bash
x-cli auth login
x-cli auth status
```

`auth login` will try to capture the browser callback automatically on your local redirect URI. If that fails (headless/SSH), it falls back to prompting for a pasted callback URL.

To clear OAuth2 tokens:

```bash
x-cli auth logout
```

x-cli checks `~/.config/x-cli/.env`, then current directory `.env`, then environment variables.

---

## Usage

### Tweets

```bash
x-cli tweet post "Hello world"
x-cli tweet post --poll "Yes,No" "Do you like polls?"
x-cli tweet get <id-or-url>
x-cli tweet delete <id-or-url>
x-cli tweet reply <id-or-url> "nice post"
x-cli tweet quote <id-or-url> "this is important"
x-cli tweet search "machine learning" --max 20
x-cli tweet metrics <id-or-url>
```

### Users

```bash
x-cli user get elonmusk
x-cli user timeline elonmusk --max 10
x-cli user followers elonmusk --max 50
x-cli user following elonmusk
```

### Self

```bash
x-cli me mentions --max 20
x-cli me bookmarks
x-cli me likes --max 20
x-cli me bookmark <id-or-url>
x-cli me unbookmark <id-or-url>
```

### Auth helpers

```bash
x-cli auth login
x-cli auth status
x-cli auth logout
```

### Quick actions

```bash
x-cli like <id-or-url>
x-cli retweet <id-or-url>
```

---

## Output Modes

Default output is compact colored panels (powered by rich). Data goes to stdout, hints to stderr.

```bash
x-cli tweet get <id>                 # human-readable (default)
x-cli -j tweet get <id>              # raw JSON, pipe to jq
x-cli -p user get elonmusk           # TSV, pipe to awk/cut
x-cli -md tweet get <id>             # markdown
x-cli -j tweet search "ai" | jq '.data[].text'
```

### Verbose

Output is compact by default (no timestamps, metrics, or metadata). Add `-v` for the full picture:

```bash
x-cli -v tweet get <id>              # human + timestamps, metrics, pagination tokens
x-cli -v -md user get elonmusk       # markdown + join date, location
x-cli -v -j tweet get <id>           # full JSON (includes, meta, everything)
```

---

## Troubleshooting

### 403 "oauth1-permissions" when posting
Your Access Token was generated before you enabled write permissions. Go to the X Developer Portal, set App permissions to "Read and write", then **Regenerate** your Access Token and Secret.

### 401 Unauthorized
Double-check all 5 credentials in your `.env`. No extra spaces or newlines.

### 429 Rate Limited
The error includes the reset timestamp. Wait until then.

### "OAuth2 login required" for bookmarks/likes
Set `X_CLIENT_ID` (and optional `X_CLIENT_SECRET`) and run:

```bash
x-cli auth login
```

### "Missing env var" on startup
x-cli looks for credentials in `~/.config/x-cli/.env`, then the current directory's `.env`, then environment variables. Make sure at least one source has all 5 values.

---

## License

MIT
