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
    "segmentFilters": [
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

conversations = []
page = 1
while True:
    body["paging"] = {"pageSize": 100, "pageNumber": page}
    resp = client.post("/api/v2/analytics/conversations/details/query", body)
    page_convs = resp.get("conversations", [])
    if not page_convs:
        break
    conversations.extend(page_convs)
    if len(page_convs) < 100:
        break
    page += 1
    if page > 20:  # safety cap — 2000 calls in a day is plenty
        break
print(f"Pulled {len(conversations)} voice conversations for {TARGET_USER_NAME} on {TARGET_DATE}")

# --- 3. Filter by phone + count by direction -----------------------------
def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

inbound = []
outbound = []
all_remote_numbers = {}  # digits -> count
sample_palmer_session = None  # raw JSON for diagnostic

# Phone fields that may contain remote numbers across Genesys versions
PHONE_FIELDS = ("ani", "dnis", "remote", "addressFrom", "addressTo",
                "addressOther", "remoteAddress", "addressSelf")

for conv in conversations:
    matched = False
    direction = None

    # Only look at participants where Palmer is the user (skip customer, IVR, queue legs)
    palmer_participants = [
        p for p in conv.get("participants", [])
        if p.get("userId") == user_id
    ]

    for participant in palmer_participants:
        for session in participant.get("sessions", []):
            # Capture the first one so we can see the real field structure
            if sample_palmer_session is None:
                sample_palmer_session = session

            sess_dir = session.get("direction") or participant.get("direction")
            for field in PHONE_FIELDS:
                val = session.get(field, "")
                if not val:
                    continue
                digits = _digits(val)
                if not digits or len(digits) < 7:
                    continue
                all_remote_numbers[digits] = all_remote_numbers.get(digits, 0) + 1
                if TARGET_PHONE_DIGITS in digits:
                    matched = True
                    if sess_dir:
                        direction = sess_dir
            if matched:
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
        outbound.append(record)

# --- 4. Print summary ----------------------------------------------------
print()
print(f"=== {TARGET_USER_NAME} <-> {TARGET_PHONE_DISPLAY} on {TARGET_DATE} ===")
print(f"Inbound calls:  {len(inbound)}")
print(f"Outbound calls: {len(outbound)}")
print(f"Total:          {len(inbound) + len(outbound)}")

if inbound or outbound:
    print("\nDetails:")
    for r in inbound + outbound:
        d = r["direction"] or "unknown"
        print(f"  [{d:<8}] {r['start']} -> {r['end']}  ({r['conversationId']})")

# Diagnostic: dump first Palmer session so we can see the actual field shape
if sample_palmer_session:
    print("\n--- Sample Palmer session (raw fields) ---")
    print(json.dumps({
        k: v for k, v in sample_palmer_session.items()
        if k in PHONE_FIELDS or k in ("direction", "sessionId", "mediaType")
    }, indent=2, default=str))

# Diagnostic: show every unique remote number we saw + the closest matches
print("\n--- Diagnostic: remote numbers observed (Palmer participants only) ---")
print(f"{len(all_remote_numbers)} unique numbers across {len(conversations)} conversations")

# Show numbers ending in last 4 of target (e.g., '7745') — likely candidates
last4 = TARGET_PHONE_DIGITS[-4:]
last7 = TARGET_PHONE_DIGITS[-7:]
print(f"\nNumbers containing last 7 of target ({last7}):")
hits7 = [(n, c) for n, c in all_remote_numbers.items() if last7 in n]
for n, c in sorted(hits7, key=lambda x: -x[1])[:20]:
    print(f"  {n}  ({c}x)")
if not hits7:
    print("  (none)")

print(f"\nTop 20 most-frequent remote numbers seen on {TARGET_DATE}:")
for n, c in sorted(all_remote_numbers.items(), key=lambda x: -x[1])[:20]:
    marker = "  <-- last 4 match" if n.endswith(last4) else ""
    print(f"  {n}  ({c}x){marker}")
