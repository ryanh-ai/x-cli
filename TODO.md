# x-cli TODOs

## ~~Use user timeline endpoint for long-range feed fetches~~ ✅ Done

`get_timeline()` now paginates via `pagination_token`, supports `start_time`/
`end_time`, and merges `username`/`name` onto tweets. `backfill-user.sh` uses
`x-cli user timeline` instead of `tweet search`, giving up to 3,200 tweets
with no 7-day window restriction.

Note: `fetch-tweets.sh` (regular feed checks) still uses combined search —
switching it to per-user timeline calls is a future option if the 7-day window
becomes a problem for infrequent feed checks.

### Why not `/tweets/search/all`?

Full-archive search requires the Enterprise tier ($42k+/month). Not viable
for personal use.
