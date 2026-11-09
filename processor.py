import logging
from typing import Any

logger = logging.getLogger(__name__)

METERS_PER_MILE = 1609.344
SHORT_WALK_MAX_MILES = 3.0
SHORT_WALK_MAX_METERS = SHORT_WALK_MAX_MILES * METERS_PER_MILE

DEFAULT_WALK_TITLES = frozenset(
    {
        "morning walk",
        "lunch walk",
        "afternoon walk",
        "evening walk",
        "night walk",
        "walk",
    }
)


def is_default_walk_title(name: str | None) -> bool:
    """Return True if the activity title matches one of Strava's default walk names."""
    if not name:
        return True
    return name.strip().lower() in DEFAULT_WALK_TITLES


def process_activity(activity: dict[str, Any]) -> dict[str, Any] | None:
    """Evaluate a Strava activity and return fields to update via PUT /activities/{id}.

    Rule:
    - If the activity is a Walk (`sport_type == "Walk"` or `type == "Walk"`),
    - has a default Strava walk title (`Morning/Lunch/Afternoon/Evening/Night Walk` or `Walk`),
    - is shorter than 3 miles (`distance < 4828.032` meters), and
    - is not already muted (`hide_from_home` is not True),
    then mute it from Home and Club feeds (`{"hide_from_home": True}`).
    """
    activity_id = activity.get("id")
    name = activity.get("name") or ""
    sport_type = activity.get("sport_type") or activity.get("type")
    distance_m = float(activity.get("distance") or 0.0)
    distance_mi = distance_m / METERS_PER_MILE
    hide_from_home = bool(activity.get("hide_from_home"))

    logger.info(
        "Evaluating activity %s: name=%r, sport_type=%s, distance=%.2fmi (%.1fm), hide_from_home=%s",
        activity_id,
        name,
        sport_type,
        distance_mi,
        distance_m,
        hide_from_home,
    )

    if sport_type == "Walk" and distance_m < SHORT_WALK_MAX_METERS and is_default_walk_title(name):
        if hide_from_home:
            logger.info("Activity %s is a short walk but already has hide_from_home=True.", activity_id)
            return None
        logger.info(
            "Muting short default-titled walk %s (%r, %.2f mi) from Home and Club feeds.",
            activity_id,
            name,
            distance_mi,
        )
        return {"hide_from_home": True}

    return None
