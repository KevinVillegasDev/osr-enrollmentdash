"""
Standalone test script for Genesys Cloud API integration.

Usage:
    python -m automation.test_genesys              # Fetch live data, update test page
    python -m automation.test_genesys --dry-run    # Fetch live data, output to console only

Requires environment variables:
    GENESYS_CLIENT_ID, GENESYS_CLIENT_SECRET, GENESYS_REGION
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone

from .config import GENESYS_REGION, GENESYS_CLIENT_ID, GENESYS_CLIENT_SECRET, PROJECT_ROOT
from .genesys_auth import GenesysClient, GenesysAuthError
from .genesys_reports import fetch_agent_talk_time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Test Genesys Cloud API")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results to console only, don't update HTML")
    args = parser.parse_args()

    # ── Validate credentials ──────────────────────────────────────────────
    if not GENESYS_CLIENT_ID or not GENESYS_CLIENT_SECRET:
        logger.error("Missing GENESYS_CLIENT_ID or GENESYS_CLIENT_SECRET environment variables.")
        logger.error("Set them via: set GENESYS_CLIENT_ID=... && set GENESYS_CLIENT_SECRET=...")
        sys.exit(1)

    logger.info("=== Genesys Cloud API Test ===")
    logger.info("Region: %s", GENESYS_REGION)
    logger.info("Client ID: %s...%s", GENESYS_CLIENT_ID[:8], GENESYS_CLIENT_ID[-4:])

    # ── Step 1: Authenticate ──────────────────────────────────────────────
    client = GenesysClient(GENESYS_REGION, GENESYS_CLIENT_ID, GENESYS_CLIENT_SECRET)
    try:
        client.authenticate()
    except GenesysAuthError as e:
        logger.error("Authentication failed: %s", e)
        _update_test_page(error=str(e))
        sys.exit(1)

    logger.info("✓ Authentication successful")

    # ── Step 2: Fetch talk time ───────────────────────────────────────────
    try:
        agents = fetch_agent_talk_time(client)
    except Exception as e:
        logger.error("Failed to fetch talk time: %s", e)
        _update_test_page(error=str(e))
        sys.exit(1)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Step 3: Display results ───────────────────────────────────────────
    logger.info("✓ Found %d agents with talk time data", len(agents))

    if agents:
        logger.info("")
        logger.info("%-30s  %12s  %8s", "Agent Name", "Talk Time", "Calls")
        logger.info("-" * 55)
        for a in agents:
            logger.info("%-30s  %12s  %8d", a["name"], a["talk_display"], a.get("calls", 0))
        logger.info("")

        total_seconds = sum(a["talk_seconds"] for a in agents)
        total_calls = sum(a.get("calls", 0) for a in agents)
        hours = total_seconds // 3600
        mins = (total_seconds % 3600) // 60
        logger.info("Total: %dh %dm talk time across %d calls", hours, mins, total_calls)
    else:
        logger.info("No talk time data found for this week. This could mean:")
        logger.info("  - No voice calls have been made this week yet")
        logger.info("  - The OAuth client doesn't have analytics permissions")
        logger.info("  - The query interval doesn't match any data")

    # ── Step 4: Update test page ──────────────────────────────────────────
    if not args.dry_run:
        _update_test_page(agents=agents, timestamp=timestamp)
        logger.info("✓ Updated genesys-test.html")
    else:
        logger.info("DRY RUN — skipping HTML update")
        logger.info("Raw JSON:")
        print(json.dumps(agents, indent=2))


def _update_test_page(agents=None, timestamp=None, error=None):
    """Inject Genesys data into the test page HTML."""
    test_path = os.path.join(PROJECT_ROOT, "genesys-test.html")

    if not os.path.exists(test_path):
        logger.warning("genesys-test.html not found at %s", test_path)
        return

    with open(test_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Build the data script block
    if error:
        data_block = f"""<script>
var genesysData = null;
var genesysTimestamp = "{timestamp or ''}";
var genesysInterval = null;
var genesysError = {json.dumps(error)};
</script>"""
    else:
        # Strip user_id from output (don't expose Genesys IDs in HTML)
        clean_agents = [
            {k: v for k, v in a.items() if k != "user_id"}
            for a in (agents or [])
        ]
        data_block = f"""<script>
var genesysData = {json.dumps(clean_agents, indent=2)};
var genesysTimestamp = "{timestamp or ''}";
var genesysInterval = "Current week (Mon-Now)";
var genesysError = null;
</script>"""

    # Replace between markers
    pattern = r'<!-- Genesys Data Start -->.*?<!-- Genesys Data End -->'
    replacement = f"<!-- Genesys Data Start -->\n{data_block}\n<!-- Genesys Data End -->"
    html = re.sub(pattern, replacement, html, flags=re.DOTALL)

    with open(test_path, "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    main()
