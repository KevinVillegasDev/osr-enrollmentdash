"""
Genesys Cloud access probe — answers "what can this OAuth client query?"

Standalone (uses requests directly; no dependency on genesys_auth internals).

Usage (PowerShell):
    $env:GENESYS_CLIENT_ID = "..."
    $env:GENESYS_CLIENT_SECRET = "..."
    $env:GENESYS_REGION = "usw2.pure.cloud"
    python automation/probe_genesys_access.py

What it does:
  1. Authenticates via OAuth 2.0 Client Credentials.
  2. Asks Genesys what roles/permissions this client holds
     (GET /api/v2/authorization/subjects/me + role detail lookups).
  3. Live-probes a battery of common endpoints and reports OK vs DENIED,
     so you get an empirical "can query / can't query" list regardless of
     how the role is configured.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

REGION = os.environ.get("GENESYS_REGION", "usw2.pure.cloud")
CID = os.environ.get("GENESYS_CLIENT_ID", "")
SECRET = os.environ.get("GENESYS_CLIENT_SECRET", "")

if not CID or not SECRET:
    print("Set GENESYS_CLIENT_ID / GENESYS_CLIENT_SECRET env vars first.")
    sys.exit(1)

LOGIN = f"https://login.{REGION}"
API = f"https://api.{REGION}"

# ── 1. Authenticate ─────────────────────────────────────────────────────────
print(f"Region: {REGION}")
r = requests.post(f"{LOGIN}/oauth/token",
                  data={"grant_type": "client_credentials"},
                  auth=(CID, SECRET), timeout=30)
if r.status_code != 200:
    print(f"AUTH FAILED ({r.status_code}): {r.text[:300]}")
    sys.exit(1)
token = r.json()["access_token"]
H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
print("AUTH OK\n")

# ── 2. Roles & permissions assigned to this client ──────────────────────────
print("=" * 70)
print("ASSIGNED ROLES / PERMISSIONS (authorization/subjects/me)")
print("=" * 70)
r = requests.get(f"{API}/api/v2/authorization/subjects/me", headers=H, timeout=30)
role_ids = []
if r.status_code == 200:
    grants = r.json().get("grants", [])
    for g in grants:
        role = g.get("role", {})
        div = g.get("division", {})
        rid = role.get("id")
        print(f"  Role: {role.get('name', rid)}  |  Division: {div.get('name', '*')}")
        if rid and rid not in role_ids:
            role_ids.append(rid)
    if not grants:
        print("  (no grants returned)")
else:
    print(f"  Cannot introspect ({r.status_code}) — falling back to endpoint probe only.")

for rid in role_ids:
    r = requests.get(f"{API}/api/v2/authorization/roles/{rid}", headers=H, timeout=30)
    if r.status_code != 200:
        print(f"  (role {rid}: detail not viewable, {r.status_code})")
        continue
    body = r.json()
    print(f"\n  Role '{body.get('name')}' permission policies:")
    for p in body.get("permissionPolicies", []):
        acts = ",".join(p.get("actionSet", [])) or "*"
        print(f"    {p.get('domain')}:{p.get('entityName') or '*'}:{acts}")

# ── 3. Endpoint probe battery ────────────────────────────────────────────────
now = datetime.now(timezone.utc)
start = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
end = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
interval = f"{start}/{end}"

PROBES = [
    # (label, method, path, json_body)
    ("Conversation aggregates (talk time, call counts)", "POST",
     "/api/v2/analytics/conversations/aggregates/query",
     {"interval": interval, "groupBy": ["userId"], "metrics": ["nConnected"]}),
    ("Conversation details (per-call records)", "POST",
     "/api/v2/analytics/conversations/details/query",
     {"interval": interval, "paging": {"pageSize": 1, "pageNumber": 1}}),
    ("User aggregates (agent status/presence time)", "POST",
     "/api/v2/analytics/users/aggregates/query",
     {"interval": interval, "groupBy": ["userId"],
      "metrics": ["tAgentRoutingStatus"]}),
    ("Users directory (names, ids, emails)", "GET",
     "/api/v2/users?pageSize=1", None),
    ("Routing queues (queue list/config)", "GET",
     "/api/v2/routing/queues?pageSize=1", None),
    ("Queue observations (real-time queue stats)", "POST",
     "/api/v2/analytics/queues/observations/query",
     {"filter": {"type": "or", "predicates": []}, "metrics": ["oOnQueueUsers"]}),
    ("Wrap-up codes", "GET", "/api/v2/routing/wrapupcodes?pageSize=1", None),
    ("Active conversations (live)", "GET",
     "/api/v2/conversations", None),
    ("Presence definitions", "GET",
     "/api/v2/presence/definitions?pageSize=1", None),
    ("Quality evaluations (QM)", "GET",
     "/api/v2/quality/evaluations/query?pageSize=1", None),
    ("Recordings settings (recording access)", "GET",
     "/api/v2/recording/settings", None),
    ("WFM management units (workforce mgmt)", "GET",
     "/api/v2/workforcemanagement/managementunits?pageSize=1", None),
    ("OAuth clients admin (client config)", "GET",
     "/api/v2/oauth/clients?pageSize=1", None),
]

print("\n" + "=" * 70)
print("LIVE ENDPOINT PROBE (OK = you can query this today)")
print("=" * 70)
for label, method, path, body in PROBES:
    try:
        if method == "GET":
            resp = requests.get(f"{API}{path}", headers=H, timeout=30)
        else:
            resp = requests.post(f"{API}{path}", headers=H,
                                 data=json.dumps(body), timeout=30)
        if resp.status_code in (200, 202):
            verdict = "OK"
        elif resp.status_code == 403:
            verdict = "DENIED (missing permission)"
        elif resp.status_code == 400:
            # 400 = request reached the API logic => permission exists
            verdict = "OK (permission present; probe body too minimal)"
        else:
            verdict = f"HTTP {resp.status_code}"
    except Exception as e:
        verdict = f"ERROR {e}"
    print(f"  [{verdict:<42}] {label}")

print("\nDone. Anything marked OK is queryable with the current client;")
print("DENIED items need a permission added to the client's role in")
print("Genesys Admin > Integrations > OAuth > (this client) > Roles.")
