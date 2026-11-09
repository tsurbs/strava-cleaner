#!/usr/bin/env python3
"""Local CLI helper for Strava OAuth authorization, webhook management, and activity testing."""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import sys
import urllib.parse
import webbrowser

from dotenv import load_dotenv, set_key
import requests

from processor import process_activity
from strava_client import STRAVA_API_BASE_URL, STRAVA_OAUTH_TOKEN_URL, StravaClient

load_dotenv()

OAUTH_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
PUSH_SUBSCRIPTIONS_URL = f"{STRAVA_API_BASE_URL}/push_subscriptions"


def _require_client_credentials() -> tuple[str, str]:
    client_id = os.environ.get("STRAVA_CLIENT_ID", "").strip()
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET", "").strip()
    if (
        not client_id
        or not client_secret
        or client_id == "your_client_id"
        or client_secret == "your_client_secret"
    ):
        print(
            "Error: Replace 'your_client_id' and 'your_client_secret' in .env with your real Strava API credentials.",
            file=sys.stderr,
        )
        sys.exit(1)
    return client_id, client_secret


def cmd_auth(args: argparse.Namespace) -> None:
    """Run a local OAuth callback server to obtain a refresh token with activity:read_all,activity:write."""
    client_id, client_secret = _require_client_credentials()
    redirect_uri = f"http://localhost:{args.port}/callback"
    scopes = "read,activity:read_all,activity:write"

    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "approval_prompt": "force",
            "scope": scopes,
        }
    )
    auth_url = f"{OAUTH_AUTHORIZE_URL}?{params}"

    captured: dict[str, str] = {}

    class OAuthCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            qs = urllib.parse.parse_qs(parsed.query)
            if "error" in qs:
                captured["error"] = qs["error"][0]
                body = f"<h2>Authorization failed: {captured['error']}</h2>"
            elif "code" in qs:
                captured["code"] = qs["code"][0]
                captured["scope"] = qs.get("scope", [""])[0]
                body = "<h2>Strava authorization received! You can close this tab and return to your terminal.</h2>"
            else:
                captured["error"] = "missing_code"
                body = "<h2>Missing code in callback.</h2>"

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, format: str, *log_args: object) -> None:
            return

    server = HTTPServer(("localhost", args.port), OAuthCallbackHandler)
    print(f"Opening browser for Strava OAuth ({scopes})...")
    print(f"If your browser does not open automatically, visit:\n\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print(f"Waiting for OAuth callback on {redirect_uri} ...")
    while "code" not in captured and "error" not in captured:
        server.handle_request()
    server.server_close()

    if "error" in captured:
        print(f"OAuth failed: {captured['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"Exchanging authorization code (granted scopes: {captured.get('scope')})...")
    resp = requests.post(
        STRAVA_OAUTH_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": captured["code"],
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    refresh_token = data["refresh_token"]
    athlete = data.get("athlete") or {}
    athlete_id = athlete.get("id", "")

    print("\nSuccess!")
    print(f"  Athlete: {athlete.get('firstname', '')} {athlete.get('lastname', '')} (ID: {athlete_id})")
    print(f"  STRAVA_REFRESH_TOKEN={refresh_token}")

    if args.save_env:
        env_path = os.path.abspath(".env")
        set_key(env_path, "STRAVA_REFRESH_TOKEN", refresh_token)
        if athlete_id:
            set_key(env_path, "STRAVA_ATHLETE_ID", str(athlete_id))
        print(f"\nSaved STRAVA_REFRESH_TOKEN and STRAVA_ATHLETE_ID to {env_path}")


def cmd_webhook_list(_args: argparse.Namespace) -> None:
    client_id, client_secret = _require_client_credentials()
    resp = requests.get(
        PUSH_SUBSCRIPTIONS_URL,
        params={"client_id": client_id, "client_secret": client_secret},
        timeout=10,
    )
    resp.raise_for_status()
    print(json.dumps(resp.json(), indent=2))


def cmd_webhook_create(args: argparse.Namespace) -> None:
    client_id, client_secret = _require_client_credentials()
    verify_token = args.verify_token or os.environ.get("STRAVA_VERIFY_TOKEN", "").strip()
    if not verify_token:
        print(
            "Error: Provide --verify-token or set STRAVA_VERIFY_TOKEN in .env",
            file=sys.stderr,
        )
        sys.exit(1)

    resp = requests.post(
        PUSH_SUBSCRIPTIONS_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "callback_url": args.callback_url,
            "verify_token": verify_token,
        },
        timeout=15,
    )
    if not resp.ok:
        print(f"Failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)
    print("Webhook subscription created:")
    print(json.dumps(resp.json(), indent=2))


def cmd_webhook_delete(args: argparse.Namespace) -> None:
    client_id, client_secret = _require_client_credentials()
    url = f"{PUSH_SUBSCRIPTIONS_URL}/{args.subscription_id}"
    resp = requests.delete(
        url,
        params={"client_id": client_id, "client_secret": client_secret},
        timeout=10,
    )
    if not resp.ok:
        print(f"Failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)
    print(f"Deleted webhook subscription {args.subscription_id}.")


def cmd_test_activity(args: argparse.Namespace) -> None:
    client = StravaClient()
    activity_id = args.activity_id
    if activity_id is None:
        recent = client.get_recent_activities(per_page=1)
        if not recent:
            print("No recent activities found on your Strava account.")
            return
        activity_id = int(recent[0]["id"])
        print(f"Using most recent activity ID: {activity_id}")

    activity = client.get_activity(activity_id)
    print(
        f"Fetched activity {activity.get('id')}: "
        f"name={activity.get('name')!r}, "
        f"sport_type={activity.get('sport_type')}, "
        f"distance={activity.get('distance')}m, "
        f"moving_time={activity.get('moving_time')}s"
    )
    updates = process_activity(activity)
    if not updates:
        print("process_activity() returned no updates.")
        return

    print("Proposed updates:")
    print(json.dumps(updates, indent=2))

    if args.apply:
        client.update_activity(activity_id, updates)
        print("Applied updates to Strava activity!")
    else:
        print("(Dry run — pass --apply to write these updates to Strava)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Strava Cleaner setup & testing CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # auth
    auth_parser = subparsers.add_parser(
        "auth",
        help="Run local OAuth flow to get a refresh token with activity:read_all,activity:write scopes",
    )
    auth_parser.add_argument("--port", type=int, default=8000, help="Local callback port (default: 8000)")
    auth_parser.add_argument(
        "--save-env",
        action="store_true",
        default=True,
        help="Save token to .env file (default: true)",
    )
    auth_parser.set_defaults(func=cmd_auth)

    # webhook
    webhook_parser = subparsers.add_parser("webhook", help="Manage Strava webhook push subscriptions")
    webhook_sub = webhook_parser.add_subparsers(dest="webhook_cmd", required=True)

    wh_list = webhook_sub.add_parser("list", help="List active webhook subscriptions")
    wh_list.set_defaults(func=cmd_webhook_list)

    wh_create = webhook_sub.add_parser("create", help="Create a webhook subscription")
    wh_create.add_argument("callback_url", help="Public HTTPS URL of your Cloud Run function")
    wh_create.add_argument("--verify-token", help="Override STRAVA_VERIFY_TOKEN")
    wh_create.set_defaults(func=cmd_webhook_create)

    wh_delete = webhook_sub.add_parser("delete", help="Delete a webhook subscription by ID")
    wh_delete.add_argument("subscription_id", type=int, help="Subscription ID to delete")
    wh_delete.set_defaults(func=cmd_webhook_delete)

    # test-activity
    test_parser = subparsers.add_parser(
        "test-activity",
        help="Fetch an existing Strava activity (defaults to latest) and run process_activity() locally",
    )
    test_parser.add_argument(
        "activity_id",
        type=int,
        nargs="?",
        default=None,
        help="Strava activity ID (omit to use your most recent activity)",
    )
    test_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually PUT the proposed updates to Strava (default is dry-run)",
    )
    test_parser.set_defaults(func=cmd_test_activity)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
