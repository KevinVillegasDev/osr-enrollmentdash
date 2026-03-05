"""
Field activity (Maps check-in) data processor.

Transforms Salesforce Maps check-in report data into the JS structures
used by field-activity.html.

Handles deduplication (multiple entries per stop → keep longest comment).
"""

import logging
from collections import defaultdict
from datetime import datetime, date

from ..config import COLUMN_LABELS, OSR_ROSTER

logger = logging.getLogger(__name__)


def process(check_in_rows: list[dict]) -> dict:
    """
    Process Maps check-in report rows into field activity data structures.

    Args:
        check_in_rows: Rows from Report 5 (Maps_Check_Ins_This_Week)

    Returns:
        Dict with repActivity, repStops, days, dayLabels, and KPI values
    """
    if not check_in_rows:
        logger.warning("No check-in data to process.")
        return _empty_result()

    # ── Parse and deduplicate stops ──────────────────────────────────────
    # Group by (rep, stop_name, date) → keep entry with longest comment
    dedup_key = {}  # (rep, stop_name, date_str) → stop dict

    for row in check_in_rows:
        rep = _get(row, "check_in_rep", "Unknown")
        stop_name = _get(row, "stop_name", "Unknown")
        check_date = _get(row, "check_in_date", "")
        comment = _get(row, "stop_comment", "")
        location = _get(row, "stop_location", "")

        # Parse date
        date_str = _format_date(check_date)
        if not date_str:
            continue

        # Existing = Account (Lead field is null/empty), Prospect = Lead (Lead field has ID)
        lead_label = COLUMN_LABELS.get("lead_field", "Lead")
        lead_val = row.get(lead_label)
        is_existing = 1 if (lead_val is None or lead_val == "" or str(lead_val) == "null") else 0

        key = (rep, stop_name, date_str)
        existing_entry = dedup_key.get(key)

        if existing_entry is None or len(comment) > len(existing_entry.get("c", "")):
            dedup_key[key] = {
                "n": stop_name,
                "d": date_str,
                "c": comment,
                "ex": is_existing,
                "l": _format_location(location),
                "_rep": rep,
            }

    # ── Build per-rep stop lists and aggregations ────────────────────────
    rep_stops_dict = defaultdict(list)
    rep_agg = defaultdict(lambda: {"total": 0, "existing": 0, "prospect": 0, "daily": defaultdict(int)})

    all_dates = set()

    for stop in dedup_key.values():
        rep = stop["_rep"]
        date_str = stop["d"]

        all_dates.add(date_str)

        # Add to stop list (without _rep internal key)
        stop_entry = {k: v for k, v in stop.items() if k != "_rep"}
        rep_stops_dict[rep].append(stop_entry)

        # Aggregate
        rep_agg[rep]["total"] += 1
        if stop["ex"] == 1:
            rep_agg[rep]["existing"] += 1
        else:
            rep_agg[rep]["prospect"] += 1
        rep_agg[rep]["daily"][date_str] += 1

    # Sort stops within each rep by date
    for rep in rep_stops_dict:
        rep_stops_dict[rep].sort(key=lambda x: x["d"])

    # ── Build repActivity array ──────────────────────────────────────────
    rep_activity = []
    for rep, agg in rep_agg.items():
        rep_activity.append({
            "n": rep,
            "t": agg["total"],
            "ex": agg["existing"],
            "pr": agg["prospect"],
            "daily": dict(agg["daily"]),
        })

    # Sort by total stops descending
    rep_activity.sort(key=lambda x: x["t"], reverse=True)

    # ── Build days and dayLabels ─────────────────────────────────────────
    sorted_dates = sorted(all_dates, key=lambda d: _parse_date_for_sort(d))

    day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    day_labels = {}
    for d in sorted_dates:
        dt = _parse_date_for_sort(d)
        if dt:
            day_labels[d] = day_names.get(dt.weekday(), "")

    # ── KPI calculations ─────────────────────────────────────────────────
    total_stops = sum(r["t"] for r in rep_activity)
    total_existing = sum(r["ex"] for r in rep_activity)
    total_prospect = sum(r["pr"] for r in rep_activity)
    reps_active = len(rep_activity)
    num_days = max(len(sorted_dates), 1)
    avg_per_day = round(total_stops / num_days, 1)

    # Date range
    if sorted_dates:
        week_start = sorted_dates[0]
        week_end = sorted_dates[-1]
    else:
        week_start = week_end = "N/A"

    logger.info(
        "Field activity: %d total stops, %d existing, %d prospect, %d reps active",
        total_stops, total_existing, total_prospect, reps_active
    )

    return {
        # JS data variables
        "repActivity": rep_activity,
        "repStops": dict(rep_stops_dict),
        "days": sorted_dates,
        "dayLabels": day_labels,
        # KPIs
        "kpi_total_stops": total_stops,
        "kpi_existing": total_existing,
        "kpi_prospect": total_prospect,
        "kpi_reps_active": f"{reps_active} / {len(OSR_ROSTER)}",
        "kpi_avg_per_day": avg_per_day,
        "kpi_week_range": f"{week_start} - {week_end}" if sorted_dates else "N/A",
    }


def _empty_result() -> dict:
    """Return an empty result structure when no data is available."""
    return {
        "repActivity": [],
        "repStops": {},
        "days": [],
        "dayLabels": {},
        "kpi_total_stops": 0,
        "kpi_existing": 0,
        "kpi_prospect": 0,
        "kpi_reps_active": f"0 / {len(OSR_ROSTER)}",
        "kpi_avg_per_day": 0,
        "kpi_week_range": "N/A",
    }


def _get(row: dict, col_key: str, default: str = "") -> str:
    label = COLUMN_LABELS.get(col_key, col_key)
    return row.get(label, default)


def _format_date(val) -> str:
    """Convert a date value to M/D/YYYY format."""
    if not val:
        return ""
    s = str(val).strip()

    # Try various formats
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ", "%m/%d/%Y", "%m/%d/%y"):
        try:
            dt = datetime.strptime(s, fmt)
            return f"{dt.month}/{dt.day}/{dt.year}"
        except ValueError:
            continue
    return s  # Return as-is if no format matches


def _format_location(location: str) -> str:
    """Clean up location string to City, State format."""
    if not location:
        return ""
    # Just return as-is; Salesforce usually provides formatted addresses
    return location.strip()


def _parse_date_for_sort(date_str: str):
    """Parse a M/D/YYYY date string into a date object for sorting."""
    try:
        parts = date_str.split("/")
        if len(parts) == 3:
            return date(int(parts[2]), int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        pass
    return date.min
