import logging
import os
from typing import Any

from dotenv import load_dotenv
from flask import Request, jsonify
import functions_framework

from processor import process_activity
from strava_client import StravaClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_client: StravaClient | None = None


def get_strava_client() -> StravaClient:
    """Return a cached StravaClient instance across warm Cloud Run invocations."""
    global _client
    if _client is None:
        _client = StravaClient()
    return _client


def is_dry_run() -> bool:
    return os.environ.get("DRY_RUN", "false").strip().lower() in {"1", "true", "yes"}


def _handle_subscription_verification(request: Request) -> tuple[Any, int]:
    """Handle Strava GET webhook verification handshake."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    expected_token = os.environ.get("STRAVA_VERIFY_TOKEN", "")
    if not expected_token:
        logger.error("STRAVA_VERIFY_TOKEN environment variable is not configured.")
        return jsonify({"error": "Server misconfigured: missing STRAVA_VERIFY_TOKEN"}), 500

    if mode == "subscribe" and token == expected_token and challenge:
        logger.info("Strava webhook verification succeeded.")
        return jsonify({"hub.challenge": challenge}), 200

    logger.warning(
        "Strava webhook verification failed (mode=%r, token_match=%s).",
        mode,
        token == expected_token,
    )
    return jsonify({"error": "Invalid verification request"}), 403


def _handle_webhook_event(request: Request) -> tuple[Any, int]:
    """Handle Strava POST webhook event notification."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400

    object_type = payload.get("object_type")
    aspect_type = payload.get("aspect_type")
    object_id = payload.get("object_id")
    owner_id = payload.get("owner_id")

    logger.info(
        "Received Strava webhook: object_type=%s, aspect_type=%s, object_id=%s, owner_id=%s",
        object_type,
        aspect_type,
        object_id,
        owner_id,
    )

    # Ignore non-activity or non-create events (importantly, ignore "update" to prevent loops)
    if object_type != "activity" or aspect_type != "create":
        return (
            jsonify(
                {
                    "status": "ignored",
                    "reason": f"Unhandled event {object_type}:{aspect_type}",
                }
            ),
            200,
        )

    expected_athlete_id = os.environ.get("STRAVA_ATHLETE_ID", "").strip()
    if expected_athlete_id and str(owner_id) != expected_athlete_id:
        logger.info(
            "Ignoring event from owner_id=%s (expected %s)",
            owner_id,
            expected_athlete_id,
        )
        return jsonify({"status": "ignored", "reason": "Athlete ID mismatch"}), 200

    if not object_id:
        return jsonify({"error": "Missing object_id"}), 400

    activity_id = int(object_id)
    client = get_strava_client()

    try:
        activity = client.get_activity(activity_id)
        updates = process_activity(activity)

        if not updates:
            logger.info("No modifications needed for activity %s.", activity_id)
            return jsonify({"status": "no_changes", "activity_id": activity_id}), 200

        if is_dry_run():
            logger.info(
                "[DRY_RUN] Would update activity %s with: %s",
                activity_id,
                updates,
            )
            return (
                jsonify(
                    {
                        "status": "dry_run",
                        "activity_id": activity_id,
                        "updates": updates,
                    }
                ),
                200,
            )

        logger.info("Updating activity %s with: %s", activity_id, updates)
        client.update_activity(activity_id, updates)
        return (
            jsonify(
                {
                    "status": "updated",
                    "activity_id": activity_id,
                    "updates": updates,
                }
            ),
            200,
        )
    except Exception as exc:
        logger.exception("Failed processing activity %s: %s", activity_id, exc)
        # Return 200 or 500? Returning 500 lets Strava retry transient network errors
        return jsonify({"error": str(exc), "activity_id": activity_id}), 500


@functions_framework.http
def webhook(request: Request) -> tuple[Any, int]:
    """Cloud Run HTTP entrypoint for Strava webhook verification and events."""
    if request.method == "GET":
        return _handle_subscription_verification(request)
    if request.method == "POST":
        return _handle_webhook_event(request)
    return jsonify({"error": f"Method {request.method} not allowed"}), 405
