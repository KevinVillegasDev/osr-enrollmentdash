"""
One-off Genesys query: Michael Palmer's inbound/outbound calls on a given day
against a specific remote phone number.

Run:  py -m automation.query_palmer_call
"""

import os
import sys
import io
import json
from datetime import datetime, timedelta, timezone

# UTF-8 stdout for the arrow chars below
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from automation.genesys_auth import GenesysClient

# --- Query parameters ----------------------------------------------------
TARGET_USER_NAME = "Michael Palmer"
TARGET_PHONE_DIGITS = "3134217745"           # raw digits we will match against
TARGET_PHONE_DISPLAY = "(313) 421-7745"
TARGET_DATE = "2025-08-07"                   # date in Pacific time

# Pacific is UTC-7 in August (PDT). Build a UTC interval covering local Aug 7.
START_UTC = datetime(2025, 8, 7, 7, 0, 0, tzinfo=timezone.utc)   # 00:00 PT
END_UTC   = datetime(2025, 8, 8, 7, 0, 0, tzinfo=timezone.utc)   # next 00:00 PT
INTERVAL  = f"{START_UTC.strftime('%Y-%m-%dT%H:%M:%S.000Z')}/{END_UTC.strftime('%Y-%m-%dT%H:%M:%S.000Z')}"

# --- Auth ----------------------------------------------------------------
client = GenesysClient(
    region=os.environ["GENESYS_REGION"],
    client_id=os.environ["GENESYS_CLIENT_ID"],
    client_secret=os.environ["GENESYS_CLIENT_SECRET"],
)
client.authenticate()

# --- 1. Resolve Michael Palmer's userId ----------------------------------
search_body = {
    "pageSize": 25,
    "pageNumber": 1,
    "query": [
        {"type": "EXACT", "fields": ["name"], "value": TARGET_USER_NAME}
    ],
}
search = client.post("/api/v2/users/search", search_body)
results = search.get("results", [])
if not results:
    print(f"No Genesys user found named '{TARGET_USER_NAME}'")
    sys.exit(1)

user_id = results[0]["id"]
print(f"Resolved {TARGET_USER_NAME} -> userId={user_id}")

# --- 2. Query conversation details for that user on that day -------------
# We filter by userId + voice mediaType, then post-filter by phone number
# in Python (avoids tel:+E.164 format mismatches).
body = {
    "interval": INTERVAL,
    "order": "asc",
    "orderBy": "conversationStart",
    "paging": {"pageSize": 100, "pageNumber": 1},
    "conversationFilters": [
        {
            "type": "and",
            "predicates": [
                {"type": "dimension", "dimension": "mediaType", "operator": "matches", "value": "voice"},
            ],
        }
    ],
    "participantFilters": [
        {
            "type": "and",
            "predicates": [
                {"type": "dimension", "dimension": "userId", "operator": "matches", "value": user_id},
            ],
        }
    ],
}

resp = client.post("/api/v2/analytics/conversations/details/query", body)
conversations = resp.get("conversations", [])
print(f"Pulled {len(conversations)} voice conversations for {TARGET_USER_NAME} on {TARGET_DATE}")

# --- 3. Filter by phone + count by direction -----------------------------
def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

inbound = []
outbound = []

for conv in conversations:
    matched = False
    direction = None

    for participant in conv.get("participants", []):
        # Look at each session for this participant for ANI/DNIS + direction
        for session in participant.get("sessions", []):
            ani = _digits(session.get("ani", ""))
            dnis = _digits(session.get("dnis", ""))
            remote = _digits(session.get("remote", ""))
            sess_dir = session.get("direction") or participant.get("direction")

            if (TARGET_PHONE_DIGITS in ani
                or TARGET_PHONE_DIGITS in dnis
                or TARGET_PHONE_DIGITS in remote):
                matched = True
                if sess_dir:
                    direction = sess_dir
                break
        if matched:
            break

    if not matched:
        continue

    record = {
        "conversationId": conv.get("conversationId"),
        "start": conv.get("conversationStart"),
        "end": conv.get("conversationEnd"),
        "direction": direction,
    }
    if direction == "inbound":
        inbound.append(record)
    elif direction == "outbound":
        outbound.append(record)
    else:
        # Direction unknown — bucket as unclassified
        outbound.append(record) if record else None

# --- 4. Print summary ----------------------------------------------------
print()
print(f"=== {TARGET_USER_NAME} <-> {TARGET_PHONE_DISPLAY} on {TARGET_DATE} ===")
print(f"Inbound calls:  {len(inbound)}")
print(f"Outbound calls: {len(outbound)}")
print(f"Total:          {len(inbound) + len(outbound)}")

if inbound or outbound:
    print("\nDetails:")
    for r in inbound + outbound:
        print(f"  [{r['direction']:<8}] {r['start']} -> {r['end']}  ({r['conversationId']})")
