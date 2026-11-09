# Strava Cleaner

Google Cloud Run function that receives Strava webhook notifications on activity upload and applies automatic cleanup rules.

## Current Rules (`processor.py`)

- **Mute short default-titled walks**: Any newly uploaded `Walk` (`sport_type == "Walk"`) shorter than **3.0 miles** (`4828m`) with a default Strava walk title (`Morning Walk`, `Lunch Walk`, `Afternoon Walk`, `Evening Walk`, `Night Walk`, or `Walk`) is automatically muted from Home and Club feeds (`hide_from_home: True`).

## Project Structure

- `main.py` — Cloud Run HTTP entrypoint (`webhook`) handling Strava `GET` subscription verification and `POST` webhook events.
- `processor.py` — Activity evaluation and modification rules (`process_activity(activity)`).
- `strava_client.py` — Strava v3 API client with in-memory OAuth token refresh caching.
- `setup_strava.py` — Local CLI for OAuth setup, webhook management, and testing against existing activities.
- `deploy.sh` — Deploys the function to Google Cloud Run (`strava-cleaner` in project `strava-cleaner-449038`, `us-central1`).
- `tests/test_webhook.py` — Unit tests for the webhook shell and processor rules.

## Common Commands

```bash
# Run unit tests
.venv/bin/python -m unittest discover -s tests -v

# Test processor logic against your latest Strava activity (dry run)
.venv/bin/python setup_strava.py test-activity

# Test against a specific activity ID and apply changes
.venv/bin/python setup_strava.py test-activity <activity_id> --apply

# List active Strava webhook subscriptions
.venv/bin/python setup_strava.py webhook list

# Redeploy after updating processor.py
./deploy.sh
```
