import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

STRAVA_OAUTH_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE_URL = "https://www.strava.com/api/v3"

# Token expiry buffer in seconds (refresh 60s before actual expiration)
EXPIRY_BUFFER_SECONDS = 60


class StravaClient:
    """Lightweight Strava v3 API client with in-memory OAuth token caching."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        timeout: int = 10,
    ) -> None:
        self.client_id = client_id or os.environ.get("STRAVA_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("STRAVA_CLIENT_SECRET", "")
        self.refresh_token = refresh_token or os.environ.get("STRAVA_REFRESH_TOKEN", "")
        self.timeout = timeout

        self._access_token: str | None = None
        self._expires_at: float = 0.0

    def _ensure_credentials(self) -> None:
        missing = [
            name
            for name, val in (
                ("STRAVA_CLIENT_ID", self.client_id),
                ("STRAVA_CLIENT_SECRET", self.client_secret),
                ("STRAVA_REFRESH_TOKEN", self.refresh_token),
            )
            if not val
        ]
        if missing:
            raise ValueError(f"Missing required Strava credentials: {', '.join(missing)}")

    def get_access_token(self) -> str:
        """Return a valid access token, refreshing via OAuth if missing or expired."""
        self._ensure_credentials()

        now = time.time()
        if self._access_token and now < (self._expires_at - EXPIRY_BUFFER_SECONDS):
            return self._access_token

        logger.info("Refreshing Strava OAuth access token...")
        response = requests.post(
            STRAVA_OAUTH_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        token_data = response.json()

        self._access_token = token_data["access_token"]
        self._expires_at = float(token_data.get("expires_at", now + 3600))

        # Keep the latest refresh token in memory in case Strava rotated it
        if token_data.get("refresh_token"):
            self.refresh_token = token_data["refresh_token"]

        return self._access_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_access_token()}"}

    def get_recent_activities(self, per_page: int = 5) -> list[dict[str, Any]]:
        """Fetch recent SummaryActivity list for the authenticated athlete."""
        url = f"{STRAVA_API_BASE_URL}/athlete/activities"
        response = requests.get(
            url,
            headers=self._headers(),
            params={"per_page": per_page},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_activity(self, activity_id: int) -> dict[str, Any]:
        """Fetch full DetailedActivity payload from Strava."""
        url = f"{STRAVA_API_BASE_URL}/activities/{activity_id}"
        response = requests.get(
            url,
            headers=self._headers(),
            params={"include_all_efforts": "false"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def update_activity(self, activity_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an activity on Strava via PUT /api/v3/activities/{id}.

        Supported fields in `updates` per Strava UpdatableActivity spec:
        - name (str)
        - description (str)
        - sport_type (str, e.g. 'Run', 'TrailRun', 'VirtualRun', 'Walk', 'Ride')
        - gear_id (str, or 'none' to clear)
        - trainer (bool)
        - commute (bool)
        - hide_from_home (bool)
        """
        url = f"{STRAVA_API_BASE_URL}/activities/{activity_id}"
        response = requests.put(
            url,
            headers=self._headers(),
            json=updates,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
