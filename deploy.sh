#!/usr/bin/env bash
set -euo pipefail

GCLOUD="${GCLOUD:-/Users/tsumacpro/google-cloud-sdk/bin/gcloud}"
PROJECT_ID="${GCP_PROJECT_ID:-strava-cleaner-449038}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-strava-cleaner}"

if [[ ! -f .env ]]; then
  echo "Error: .env file not found" >&2
  exit 1
fi

set -a
source .env
set +a

ENV_VARS="STRAVA_CLIENT_ID=${STRAVA_CLIENT_ID},STRAVA_CLIENT_SECRET=${STRAVA_CLIENT_SECRET},STRAVA_REFRESH_TOKEN=${STRAVA_REFRESH_TOKEN},STRAVA_VERIFY_TOKEN=${STRAVA_VERIFY_TOKEN},STRAVA_ATHLETE_ID=${STRAVA_ATHLETE_ID:-},DRY_RUN=${DRY_RUN:-false}"

echo "Deploying ${SERVICE_NAME} to Cloud Run (project=${PROJECT_ID}, region=${REGION})..."
"$GCLOUD" run deploy "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --source=. \
  --function=webhook \
  --base-image=python312 \
  --allow-unauthenticated \
  --max-instances=3 \
  --memory=256Mi \
  --set-env-vars="$ENV_VARS" \
  --quiet
