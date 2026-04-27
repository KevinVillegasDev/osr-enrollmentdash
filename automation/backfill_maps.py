"""One-shot: backfill Maps check-in snapshots for past months by overriding the SF date filter.

Reuses the existing fetch_maps_check_ins_split logic to pull each target month in halves
(2,000-row API cap workaround). Run once via the dashboard's GitHub Actions workflow_dispatch,
verify the snapshot files land, then delete this script and its workflow.

Edit MONTHS below before running.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Allow running as `python -m automation.backfill_maps` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from automation.config import SF_CLIENT_ID, SF_CLIENT_SECRET, SF_LOGIN_URL
from automation.salesforce_auth import SalesforceClient
from automation.salesforce_reports import fetch_maps_check_ins_split

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_maps")

# (year, month) tuples to backfill. Edit before running.
MONTHS: list[tuple[int, int]] = [(2026, 1), (2026, 2)]

# Each split fetch caps at 2000 rows. If a half hits the cap exactly, the data was likely
# truncated; the fetch needs more granular splits. We just warn for now — most months
# under-2000 per half is expected for past months when the team was smaller.
SUSPICIOUS_HALF_THRESHOLD = 2000


def main() -> None:
    if not SF_CLIENT_ID or not SF_CLIENT_SECRET:
        logger.error("SF_CLIENT_ID / SF_CLIENT_SECRET not set in env. Aborting.")
        sys.exit(1)

    client = SalesforceClient(SF_LOGIN_URL, SF_CLIENT_ID, SF_CLIENT_SECRET)
    client.authenticate()

    project_root = Path(__file__).resolve().parent.parent

    for year, month in MONTHS:
        logger.info("=== Backfilling %d-%02d ===", year, month)
        rows = fetch_maps_check_ins_split(client, month, year)
        if not rows:
            logger.warning("No rows returned for %d-%02d, skipping write.", year, month)
            continue

        # Sanity flag if either half looks truncated.
        if len(rows) >= SUSPICIOUS_HALF_THRESHOLD * 2:
            logger.warning(
                "%d-%02d returned %d rows — verify neither half hit the 2,000-row cap. "
                "If so, this month needs finer splits.",
                year, month, len(rows),
            )

        snap_dir = project_root / "data" / "snapshots" / f"{year}-{month:02d}"
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_path = snap_dir / "maps_check_ins.json"
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, default=str)
        logger.info("Wrote %s (%d rows)", snap_path, len(rows))


if __name__ == "__main__":
    main()
