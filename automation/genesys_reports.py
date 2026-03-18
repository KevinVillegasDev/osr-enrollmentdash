"""
Genesys Cloud Analytics API client.

Fetches agent talk time data via the Conversation Aggregates endpoint.
Groups by userId and resolves display names via the Users API.
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def fetch_agent_talk_time(client, interval: str = None) -> list[dict]:
    """
    Fetch total talk time per agent for the given interval.

    Uses POST /api/v2/analytics/conversations/aggregates/query to get
    tTalk (total talk seconds) grouped by userId, then resolves each
    userId to a display name via GET /api/v2/users/{userId}.

    Args:
        client: Authenticated GenesysClient instance.
        interval: ISO-8601 interval string (e.g., '2026-03-17T00:00:00Z/2026-03-18T23:59:59Z').
                  Defaults to current week (Monday 00:00 UTC through now).

    Returns:
        List of dicts: [{"name": "Agent Name", "talk_seconds": 12345, "talk_display": "3h 25m"}, ...]
        Sorted by talk_seconds descending.
    """
    if not interval:
        interval = _current_week_interval()

    logger.info("Fetching Genesys talk time for interval: %s", interval)

    # Query aggregate talk time grouped by userId
    body = {
        "interval": interval,
        "granularity": "PT24H",
        "groupBy": ["userId"],
        "metrics": ["tTalk"],
        "filter": {
            "type": "and",
            "predicates": [
                {
                    "dimension": "mediaType",
                    "value": "voice",
                },
            ],
        },
    }

    try:
        resp = client.post("/api/v2/analytics/conversations/aggregates/query", body)
    except Exception as e:
        logger.error("Failed to fetch conversation aggregates: %s", e)
        return []

    # Parse response — extract userId → total tTalk and nConnected
    user_talk = {}
    user_calls = {}

    results = resp.get("results", [])

    # Log first result for debugging response structure
    if results:
        import json as _json
        logger.info("Genesys response sample (first result): %s",
                     _json.dumps(results[0], indent=2, default=str)[:2000])

    for result in results:
        group = result.get("group", {})
        user_id = group.get("userId")
        if not user_id:
            continue

        # Sum across all date buckets
        total_talk = 0
        total_calls = 0
        for data_item in result.get("data", []):
            metrics = data_item.get("metrics", [])
            for metric in metrics:
                metric_name = metric.get("metric", "")
                stats = metric.get("stats", {})
                if metric_name == "tTalk":
                    # tTalk stats.sum = total milliseconds, stats.count = number of talk segments
                    total_talk += stats.get("sum", 0)
                    total_calls += int(stats.get("count", 0))

        user_talk[user_id] = user_talk.get(user_id, 0) + total_talk
        user_calls[user_id] = user_calls.get(user_id, 0) + total_calls

    logger.info("Found talk time data for %d users", len(user_talk))

    # Resolve userIds to display names
    agents = []
    for user_id, talk_ms in user_talk.items():
        name = _resolve_user_name(client, user_id)
        talk_seconds = int(talk_ms / 1000) if talk_ms > 1000 else int(talk_ms)
        agents.append({
            "user_id": user_id,
            "name": name,
            "talk_seconds": talk_seconds,
            "talk_display": _format_duration(talk_seconds),
            "calls": user_calls.get(user_id, 0),
        })

    # Sort by talk time descending
    agents.sort(key=lambda a: a["talk_seconds"], reverse=True)

    return agents


def _resolve_user_name(client, user_id: str) -> str:
    """Look up a Genesys user's display name by userId."""
    try:
        user = client.get(f"/api/v2/users/{user_id}")
        return user.get("name", user_id)
    except Exception as e:
        logger.warning("Could not resolve userId %s: %s", user_id, e)
        return user_id


def _current_week_interval() -> str:
    """
    Build an ISO-8601 interval for current week (Monday 00:00 UTC → now).
    """
    now = datetime.now(timezone.utc)
    # Monday of current week
    monday = now - timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)

    start = monday.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    return f"{start}/{end}"


def _format_duration(total_seconds: int) -> str:
    """Format seconds into human-readable duration (e.g., '3h 25m')."""
    if total_seconds <= 0:
        return "0m"

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60

    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"
