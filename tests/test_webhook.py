import os
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

import main
from processor import process_activity


class WebhookShellTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = Flask(__name__)
        main._client = None
        os.environ["STRAVA_VERIFY_TOKEN"] = "secret-verify-token"
        os.environ["STRAVA_CLIENT_ID"] = "12345"
        os.environ["STRAVA_CLIENT_SECRET"] = "secret"
        os.environ["STRAVA_REFRESH_TOKEN"] = "refresh"
        os.environ.pop("STRAVA_ATHLETE_ID", None)
        os.environ["DRY_RUN"] = "false"

    def test_get_verification_success(self) -> None:
        with self.app.test_request_context(
            "/?hub.mode=subscribe&hub.verify_token=secret-verify-token&hub.challenge=15f7d1a91c1f40f8a748fd134752feb3",
            method="GET",
        ) as ctx:
            resp, status = main.webhook(ctx.request)
            self.assertEqual(status, 200)
            self.assertEqual(
                resp.get_json(),
                {"hub.challenge": "15f7d1a91c1f40f8a748fd134752feb3"},
            )

    def test_get_verification_forbidden_on_bad_token(self) -> None:
        with self.app.test_request_context(
            "/?hub.mode=subscribe&hub.verify_token=wrong-token&hub.challenge=abc",
            method="GET",
        ) as ctx:
            resp, status = main.webhook(ctx.request)
            self.assertEqual(status, 403)

    def test_post_ignores_update_events(self) -> None:
        payload = {
            "object_type": "activity",
            "aspect_type": "update",
            "object_id": 999,
            "owner_id": 42,
        }
        with self.app.test_request_context("/", method="POST", json=payload) as ctx:
            resp, status = main.webhook(ctx.request)
            self.assertEqual(status, 200)
            self.assertEqual(resp.get_json()["status"], "ignored")

    @patch("main.process_activity")
    @patch("main.get_strava_client")
    def test_post_create_event_no_changes(
        self, mock_get_client: MagicMock, mock_process: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client.get_activity.return_value = {
            "id": 1001,
            "name": "Morning Run",
            "sport_type": "Run",
        }
        mock_get_client.return_value = mock_client
        mock_process.return_value = None

        payload = {
            "object_type": "activity",
            "aspect_type": "create",
            "object_id": 1001,
            "owner_id": 42,
        }
        with self.app.test_request_context("/", method="POST", json=payload) as ctx:
            resp, status = main.webhook(ctx.request)
            self.assertEqual(status, 200)
            self.assertEqual(
                resp.get_json(),
                {"status": "no_changes", "activity_id": 1001},
            )
            mock_client.get_activity.assert_called_once_with(1001)
            mock_client.update_activity.assert_not_called()

    @patch("main.process_activity")
    @patch("main.get_strava_client")
    def test_post_create_event_updates_activity(
        self, mock_get_client: MagicMock, mock_process: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client.get_activity.return_value = {
            "id": 1002,
            "name": "Morning Run",
            "sport_type": "Run",
        }
        mock_get_client.return_value = mock_client
        mock_process.return_value = {"name": "Cleaned Run", "hide_from_home": True}

        payload = {
            "object_type": "activity",
            "aspect_type": "create",
            "object_id": 1002,
            "owner_id": 42,
        }
        with self.app.test_request_context("/", method="POST", json=payload) as ctx:
            resp, status = main.webhook(ctx.request)
            self.assertEqual(status, 200)
            self.assertEqual(resp.get_json()["status"], "updated")
            mock_client.update_activity.assert_called_once_with(
                1002, {"name": "Cleaned Run", "hide_from_home": True}
            )

    @patch("main.process_activity")
    @patch("main.get_strava_client")
    def test_post_create_event_dry_run(
        self, mock_get_client: MagicMock, mock_process: MagicMock
    ) -> None:
        os.environ["DRY_RUN"] = "true"
        mock_client = MagicMock()
        mock_client.get_activity.return_value = {
            "id": 1003,
            "name": "Morning Run",
            "sport_type": "Run",
        }
        mock_get_client.return_value = mock_client
        mock_process.return_value = {"name": "Dry Run Name"}

        payload = {
            "object_type": "activity",
            "aspect_type": "create",
            "object_id": 1003,
            "owner_id": 42,
        }
        with self.app.test_request_context("/", method="POST", json=payload) as ctx:
            resp, status = main.webhook(ctx.request)
            self.assertEqual(status, 200)
            self.assertEqual(resp.get_json()["status"], "dry_run")
            mock_client.update_activity.assert_not_called()


class ProcessorTests(unittest.TestCase):
    def test_short_default_walk_is_muted(self) -> None:
        activity = {
            "id": 20902203411,
            "name": "Afternoon Walk",
            "sport_type": "Walk",
            "distance": 3138.0,  # ~1.95 miles
            "hide_from_home": False,
        }
        self.assertEqual(process_activity(activity), {"hide_from_home": True})

    def test_already_muted_short_walk_returns_none(self) -> None:
        activity = {
            "id": 20913273571,
            "name": "Lunch Walk",
            "sport_type": "Walk",
            "distance": 1097.8,
            "hide_from_home": True,
        }
        self.assertIsNone(process_activity(activity))

    def test_walk_over_three_miles_is_not_muted(self) -> None:
        activity = {
            "id": 100,
            "name": "Morning Walk",
            "sport_type": "Walk",
            "distance": 5000.0,  # ~3.11 miles
            "hide_from_home": False,
        }
        self.assertIsNone(process_activity(activity))

    def test_short_walk_with_custom_title_is_not_muted(self) -> None:
        activity = {
            "id": 101,
            "name": "Coffee stroll",
            "sport_type": "Walk",
            "distance": 1500.0,
            "hide_from_home": False,
        }
        self.assertIsNone(process_activity(activity))

    def test_short_run_is_not_muted(self) -> None:
        activity = {
            "id": 102,
            "name": "Morning Run",
            "sport_type": "Run",
            "distance": 2000.0,
            "hide_from_home": False,
        }
        self.assertIsNone(process_activity(activity))


if __name__ == "__main__":
    unittest.main()
