"""Click CLI for x-cli."""

from __future__ import annotations

from datetime import datetime, timezone

import click

from .api import XApiClient
from .auth import load_auth_context
from .formatters import format_output
from .utils import parse_tweet_id, strip_at


class State:
    def __init__(self, mode: str, verbose: bool = False) -> None:
        self.mode = mode
        self.verbose = verbose
        self._client: XApiClient | None = None

    @property
    def client(self) -> XApiClient:
        if self._client is None:
            creds, oauth2 = load_auth_context()
            self._client = XApiClient(creds, oauth2)
        return self._client

    def output(self, data, title: str = "") -> None:
        format_output(data, self.mode, title, verbose=self.verbose)


pass_state = click.make_pass_decorator(State)


@click.group()
@click.option("--json", "-j", "fmt", flag_value="json", help="JSON output")
@click.option("--plain", "-p", "fmt", flag_value="plain", help="TSV output for piping")
@click.option("--markdown", "-md", "fmt", flag_value="markdown", help="Markdown output")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Verbose output (show metrics, timestamps, metadata)")
@click.pass_context
def cli(ctx, fmt, verbose):
    """x-cli: CLI for X/Twitter API v2."""
    ctx.ensure_object(dict)
    ctx.obj = State(fmt or "human", verbose=verbose)


# ============================================================
# auth
# ============================================================


@cli.group()
def auth():
    """OAuth2 auth management."""


@auth.command("login")
def auth_login():
    """Run OAuth2 PKCE login flow and save tokens."""
    from .xdk_auth import load_oauth2_manager

    manager = load_oauth2_manager()
    if not manager:
        raise click.ClickException("Missing X_CLIENT_ID. Set it in ~/.config/x-cli/.env and retry.")

    try:
        session = manager.login_interactive()
    except Exception as e:
        raise click.ClickException(str(e)) from e

    click.echo("OAuth2 login successful.")
    click.echo(f"Scopes: {session.scope}")


@auth.command("status")
def auth_status():
    """Show OAuth2 token status."""
    from .xdk_auth import load_oauth2_manager

    manager = load_oauth2_manager()
    if not manager:
        click.echo("OAuth2 config: not configured (set X_CLIENT_ID)")
        return

    session = manager.load_session()
    if not session:
        click.echo("OAuth2 session: not logged in")
        return

    expires = datetime.fromtimestamp(session.expires_at, tz=timezone.utc).isoformat()
    state = "expired" if session.is_expired(skew=0) else "valid"
    click.echo(f"OAuth2 session: {state}")
    click.echo(f"Expires (UTC): {expires}")
    click.echo(f"Scopes: {session.scope}")


@auth.command("logout")
def auth_logout():
    """Clear OAuth2 tokens."""
    from .xdk_auth import load_oauth2_manager

    manager = load_oauth2_manager()
    if not manager:
        click.echo("OAuth2 config not set; nothing to do.")
        return

    manager.logout()
    click.echo("OAuth2 session cleared.")


# ============================================================
# tweet
# ============================================================


@cli.group()
def tweet():
    """Tweet operations."""


@tweet.command("post")
@click.argument("text")
@click.option("--poll", default=None, help="Comma-separated poll options")
@click.option("--poll-duration", default=1440, type=int, help="Poll duration in minutes")
@pass_state
def tweet_post(state, text, poll, poll_duration):
    """Post a tweet."""
    poll_options = [o.strip() for o in poll.split(",")] if poll else None
    data = state.client.post_tweet(text, poll_options=poll_options, poll_duration_minutes=poll_duration)
    state.output(data, "Posted")


@tweet.command("get")
@click.argument("id_or_url")
@pass_state
def tweet_get(state, id_or_url):
    """Fetch a tweet by ID or URL."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.get_tweet(tid)
    state.output(data, f"Tweet {tid}")


@tweet.command("delete")
@click.argument("id_or_url")
@pass_state
def tweet_delete(state, id_or_url):
    """Delete a tweet."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.delete_tweet(tid)
    state.output(data, "Deleted")


@tweet.command("reply")
@click.argument("id_or_url")
@click.argument("text")
@pass_state
def tweet_reply(state, id_or_url, text):
    """Reply to a tweet."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.post_tweet(text, reply_to=tid)
    state.output(data, "Reply")


@tweet.command("quote")
@click.argument("id_or_url")
@click.argument("text")
@pass_state
def tweet_quote(state, id_or_url, text):
    """Quote tweet."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.post_tweet(text, quote_tweet_id=tid)
    state.output(data, "Quote")


@tweet.command("search")
@click.argument("query")
@click.option("--max", "max_results", default=100, type=int, help="Max total results (paginates automatically, default 100)")
@click.option("--start-time", default=None, help="Filter start time (ISO 8601, e.g. 2026-02-20T00:00:00Z)")
@click.option("--end-time", default=None, help="Filter end time (ISO 8601, e.g. 2026-02-28T23:59:59Z)")
@pass_state
def tweet_search(state, query, max_results, start_time, end_time):
    """Search recent tweets."""
    data = state.client.search_tweets(query, max_results, start_time=start_time, end_time=end_time)
    state.output(data, f"Search: {query}")


@tweet.command("metrics")
@click.argument("id_or_url")
@pass_state
def tweet_metrics(state, id_or_url):
    """Get tweet engagement metrics."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.get_tweet_metrics(tid)
    state.output(data, f"Metrics {tid}")


# ============================================================
# user
# ============================================================


@cli.group()
def user():
    """User operations."""


@user.command("get")
@click.argument("username")
@pass_state
def user_get(state, username):
    """Look up a user profile."""
    data = state.client.get_user(strip_at(username))
    state.output(data, f"@{strip_at(username)}")


@user.command("timeline")
@click.argument("username")
@click.option("--max", "max_results", default=100, type=int, help="Max total results (paginates automatically, default 100, up to 3200)")
@click.option("--start-time", "start_time", default=None, help="Only tweets after this time (ISO 8601, e.g. 2026-02-01T00:00:00Z)")
@click.option("--end-time", "end_time", default=None, help="Only tweets before this time (ISO 8601)")
@pass_state
def user_timeline(state, username, max_results, start_time, end_time):
    """Fetch a user's recent tweets (up to 3,200, no 7-day limit)."""
    uname = strip_at(username)
    user_data = state.client.get_user(uname)
    uid = user_data["data"]["id"]
    data = state.client.get_timeline(uid, max_results, start_time=start_time, end_time=end_time)
    state.output(data, f"@{uname} timeline")


@user.command("followers")
@click.argument("username")
@click.option("--max", "max_results", default=100, type=int, help="Max results (1-1000)")
@pass_state
def user_followers(state, username, max_results):
    """List a user's followers."""
    uname = strip_at(username)
    user_data = state.client.get_user(uname)
    uid = user_data["data"]["id"]
    data = state.client.get_followers(uid, max_results)
    state.output(data, f"@{uname} followers")


@user.command("following")
@click.argument("username")
@click.option("--max", "max_results", default=100, type=int, help="Max results (1-1000)")
@pass_state
def user_following(state, username, max_results):
    """List who a user follows."""
    uname = strip_at(username)
    user_data = state.client.get_user(uname)
    uid = user_data["data"]["id"]
    data = state.client.get_following(uid, max_results)
    state.output(data, f"@{uname} following")


# ============================================================
# me
# ============================================================


@cli.group()
def me():
    """Self operations (authenticated user)."""


@me.command("mentions")
@click.option("--max", "max_results", default=10, type=int, help="Max results (5-100)")
@pass_state
def me_mentions(state, max_results):
    """Fetch your recent mentions."""
    data = state.client.get_mentions(max_results)
    state.output(data, "Mentions")


@me.command("bookmarks")
@click.option("--max", "max_results", default=10, type=int, help="Max results (1-100)")
@pass_state
def me_bookmarks(state, max_results):
    """Fetch your bookmarks."""
    data = state.client.get_bookmarks(max_results)
    state.output(data, "Bookmarks")


@me.command("likes")
@click.option("--max", "max_results", default=10, type=int, help="Max results (1-100)")
@pass_state
def me_likes(state, max_results):
    """Fetch your liked tweets."""
    data = state.client.get_likes(max_results)
    state.output(data, "Likes")


@me.command("bookmark")
@click.argument("id_or_url")
@pass_state
def me_bookmark(state, id_or_url):
    """Bookmark a tweet."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.bookmark_tweet(tid)
    state.output(data, "Bookmarked")


@me.command("unbookmark")
@click.argument("id_or_url")
@pass_state
def me_unbookmark(state, id_or_url):
    """Remove a bookmark."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.unbookmark_tweet(tid)
    state.output(data, "Unbookmarked")


# ============================================================
# quick actions (top-level)
# ============================================================


@cli.command("like")
@click.argument("id_or_url")
@pass_state
def like(state, id_or_url):
    """Like a tweet."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.like_tweet(tid)
    state.output(data, "Liked")


@cli.command("retweet")
@click.argument("id_or_url")
@pass_state
def retweet(state, id_or_url):
    """Retweet a tweet."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.retweet(tid)
    state.output(data, "Retweeted")


def main():
    try:
        cli()
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e


if __name__ == "__main__":
    main()
