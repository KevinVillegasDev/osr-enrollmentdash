"""
Field activity (Maps check-in) data processor.

Transforms Salesforce Maps check-in report data into the JS structures
used by field-activity.html.

Report 5 now pulls THIS MONTH (all check-ins for the current calendar month).
Column is "Created Date/Time" with format "M/D/YYYY, H:MM AM/PM".
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

        # Parse date and time from the combined field
        date_str, time_str, sort_key = _parse_datetime(check_date)
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
                "t": time_str,      # Time string e.g. "5:40 AM"
                "sk": sort_key,     # ISO sort key for ordering
                "c": comment,
                "ex": is_existing,
                "l": _format_location(location),
                "_rep": rep,
            }

    # ── Build per-rep stop lists and aggregations ────────────────────────
    rep_stops_dict = defaultdict(list)
    rep_agg = defaultdict(lambda: {"total": 0, "existing": 0, "prospect": 0, "daily": defaultdict(int)})

    all_dates = set()

    # Collect timestamps per (rep, date) for avg hours calculation
    rep_day_timestamps = defaultdict(lambda: defaultdict(list))  # rep → date → [sort_key, ...]

    for stop in dedup_key.values():
        rep = stop["_rep"]
        date_str = stop["d"]

        all_dates.add(date_str)

        # Collect sort key timestamps for hours-in-field calculation
        if stop.get("sk"):
            rep_day_timestamps[rep][date_str].append(stop["sk"])

        # Add to stop list (without internal keys)
        stop_entry = {k: v for k, v in stop.items() if k not in ("_rep", "sk")}
        rep_stops_dict[rep].append(stop_entry)

        # Aggregate
        rep_agg[rep]["total"] += 1
        if stop["ex"] == 1:
            rep_agg[rep]["existing"] += 1
        else:
            rep_agg[rep]["prospect"] += 1
        rep_agg[rep]["daily"][date_str] += 1

    # Sort stops within each rep by datetime (using the sort key)
    for rep in rep_stops_dict:
        rep_stops_dict[rep].sort(key=lambda x: x.get("t", "") if x["d"] == x["d"] else x["d"])

    # Better sort: reconstruct sort keys from date + time for ordering
    for rep in rep_stops_dict:
        rep_stops_dict[rep].sort(key=lambda x: _stop_sort_key(x))

    # ── Compute avg hours in field per rep ────────────────────────────────
    rep_avg_hours = {}
    for rep, day_map in rep_day_timestamps.items():
        daily_spans = []
        for date_str, timestamps in day_map.items():
            if len(timestamps) < 2:
                continue  # Need at least 2 stops to compute a span
            sorted_ts = sorted(timestamps)
            first = sorted_ts[0]   # e.g. "2026-03-02 08:40"
            last = sorted_ts[-1]
            try:
                first_dt = datetime.strptime(first, "%Y-%m-%d %H:%M")
                last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M")
                span_hours = (last_dt - first_dt).total_seconds() / 3600
                if span_hours > 0:
                    daily_spans.append(span_hours)
            except ValueError:
                continue
        if daily_spans:
            rep_avg_hours[rep] = round(sum(daily_spans) / len(daily_spans), 1)
        else:
            rep_avg_hours[rep] = 0

    # ── Build repActivity array ──────────────────────────────────────────
    rep_activity = []
    for rep, agg in rep_agg.items():
        rep_activity.append({
            "n": rep,
            "t": agg["total"],
            "ex": agg["existing"],
            "pr": agg["prospect"],
            "daily": dict(agg["daily"]),
            "avg_hours": rep_avg_hours.get(rep, 0),
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
        month_start = sorted_dates[0]
        month_end = sorted_dates[-1]
    else:
        month_start = month_end = "N/A"

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
        "kpi_month_range": f"{month_start} - {month_end}" if sorted_dates else "N/A",
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


def _parse_datetime(val) -> tuple:
    """
    Parse a date/time value into (date_str, time_str, sort_key).

    Handles formats:
    - "3/2/2026, 5:40 AM"  (Salesforce _label_ display format)
    - "2026-03-02T13:40:06Z" (ISO)
    - "3/2/2026" (legacy date-only)
    - "2026-03-02" (ISO date-only)

    Returns:
        Tuple of (date_str "M/D/YYYY", time_str "H:MM AM" or "", sort_key "YYYY-MM-DD HH:MM")
    """
    if not val:
        return ("", "", "")
    s = str(val).strip()

    # Format: "3/2/2026, 5:40 AM" or "3/2/2026, 12:30 PM"
    if ", " in s and ("AM" in s.upper() or "PM" in s.upper()):
        try:
            date_part, time_part = s.split(", ", 1)
            # Parse date
            dp = date_part.split("/")
            if len(dp) == 3:
                month, day, year = int(dp[0]), int(dp[1]), int(dp[2])
                date_str = f"{month}/{day}/{year}"

                # Parse time — handle both "5:40 AM" and "12:30 PM"
                time_str = time_part.strip()

                # Build sort key
                dt = _parse_time_to_24h(time_str)
                sort_key = f"{year:04d}-{month:02d}-{day:02d} {dt}"
                return (date_str, time_str, sort_key)
        except (ValueError, IndexError):
            pass

    # Format: "2026-03-02T13:40:06Z" or "2026-03-02T13:40:06.000Z"
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            dt = datetime.strptime(s, fmt)
            date_str = f"{dt.month}/{dt.day}/{dt.year}"
            # Convert UTC to CT (UTC-6 for CST, UTC-5 for CDT)
            # March = CDT (UTC-5)
            ct_hour = (dt.hour - 5) % 24
            ampm = "AM" if ct_hour < 12 else "PM"
            display_hour = ct_hour % 12
            if display_hour == 0:
                display_hour = 12
            time_str = f"{display_hour}:{dt.minute:02d} {ampm}"
            sort_key = f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d} {ct_hour:02d}:{dt.minute:02d}"
            return (date_str, time_str, sort_key)
        except ValueError:
            continue

    # Legacy format: "M/D/YYYY" (date only, no time)
    try:
        parts = s.split("/")
        if len(parts) == 3:
            month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
            date_str = f"{month}/{day}/{year}"
            return (date_str, "", f"{year:04d}-{month:02d}-{day:02d} 00:00")
    except (ValueError, IndexError):
        pass

    # Legacy format: "YYYY-MM-DD" (date only)
    try:
        dt = datetime.strptime(s, "%Y-%m-%d")
        return (f"{dt.month}/{dt.day}/{dt.year}", "", f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d} 00:00")
    except ValueError:
        pass

    return (s, "", "")  # Return as-is if no format matches


def _parse_time_to_24h(time_str: str) -> str:
    """Convert '5:40 AM' or '12:30 PM' to '05:40' 24-hour format for sorting."""
    try:
        time_str = time_str.strip().upper()
        is_pm = "PM" in time_str
        time_str = time_str.replace("AM", "").replace("PM", "").strip()
        parts = time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0

        if is_pm and hour != 12:
            hour += 12
        elif not is_pm and hour == 12:
            hour = 0

        return f"{hour:02d}:{minute:02d}"
    except (ValueError, IndexError):
        return "00:00"


def _stop_sort_key(stop: dict) -> str:
    """Generate a sort key from a stop's date and time for chronological ordering."""
    d = stop.get("d", "")
    t = stop.get("t", "")
    try:
        parts = d.split("/")
        if len(parts) == 3:
            month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
            time_24h = _parse_time_to_24h(t) if t else "00:00"
            return f"{year:04d}-{month:02d}-{day:02d} {time_24h}"
    except (ValueError, IndexError):
        pass
    return d


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
