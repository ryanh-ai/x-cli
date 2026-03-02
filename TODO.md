# x-cli TODOs

## Use user timeline endpoint for long-range feed fetches

`/tweets/search/recent` is limited to a 7-day window (Basic/Pro tiers).
The `/2/users/:id/tweets` timeline endpoint has no such restriction and supports
`start_time`/`end_time` freely — making it better for feed checks that span
weeks or months (e.g. `last_checked` > 7 days ago).

### What needs to change

- **`api.py` — `get_timeline()`**: add `start_time`/`end_time` params and a
  `next_token` pagination loop (same pattern as the updated `search_tweets()`).

- **`cli.py` — `user timeline`**: expose `--start-time` and `--end-time` options,
  remove the 100-result cap (pagination handles it now).

- **`fetch-tweets.sh`** (check-tweets skill): switch to per-user timeline calls
  when `--since` is older than 7 days, falling back to the combined `search`
  query for recent-only fetches. Tradeoff: ~1 API call per account (19 for the
  current feed) vs. 1 combined search call, but correct date coverage.

### Why not `/tweets/search/all`?

Full-archive search requires the Enterprise tier ($42k+/month). Not viable
for personal use.
