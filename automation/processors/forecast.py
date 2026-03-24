"""
Forecast / pacing data processor.

Takes territory-level budget targets and actuals from either:
  1. Live Salesforce Monthly Quota report (Report 6) — preferred
  2. Static forecast_data.py — fallback

Maps territories to OSRs via config.TERRITORY_MAP, and produces
per-rep forecast projections including MTD pacing, end-of-month projection,
and year-to-date variance.

Outputs: Dict with per-rep forecast data and team-level aggregates.
"""

import logging
from datetime import datetime, date, timedelta

from ..config import TERRITORY_MAP, MONTH_NAMES, OSR_ROSTER

logger = logging.getLogger(__name__)


def _business_days_in_month(year: int, month: int) -> int:
    """Count total business days (Mon-Fri) in a given month."""
    count = 0
    d = date(year, month, 1)
    # Advance to next month to find end of this month
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    while d < end:
        if d.weekday() < 5:  # Monday=0 through Friday=4
            count += 1
        d += timedelta(days=1)
    return count


def _business_days_elapsed(year: int, month: int, through_date: date) -> int:
    """Count business days elapsed from start of month through through_date (inclusive)."""
    count = 0
    d = date(year, month, 1)
    end = min(through_date, date(year, month + 1, 1) - timedelta(days=1)) if month < 12 \
        else min(through_date, date(year, 12, 31))

    while d <= end:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def process_forecast(current_date=None, quota_rows=None) -> dict:
    """
    Process budget targets and actuals into per-rep forecast data.

    Args:
        current_date: Override for today's date (datetime or date). Defaults to now.
        quota_rows: Optional list of parsed rows from Report 6 (Monthly Quota).
                   If provided, uses live Salesforce data instead of static forecast_data.

    Returns:
        Dict with month info, per-rep forecasts (sorted by variance descending),
        and team-level aggregates.
    """
    if current_date is None:
        current_date = datetime.now()
    if isinstance(current_date, datetime):
        current_date = current_date.date()

    year = current_date.year
    month_num = current_date.month
    month_name = MONTH_NAMES[month_num]

    # ── Business day calculations for the current MTD month ───────────────
    biz_days_total = _business_days_in_month(year, month_num)
    biz_days_elapsed = _business_days_elapsed(year, month_num, current_date)

    if biz_days_elapsed == 0:
        logger.warning("No business days elapsed yet in %s %d; projections will use 1 day.",
                        month_name, year)
        biz_days_elapsed = 1  # Avoid division by zero

    logger.info("Forecast: %s %d — %d/%d business days elapsed",
                month_name, year, biz_days_elapsed, biz_days_total)

    # ── Build per-rep forecast data ───────────────────────────────────────
    reps = []

    if quota_rows:
        # ── LIVE MODE: Use Salesforce Monthly Quota report ────────────────
        reps = _process_from_quota_report(quota_rows, year, month_num,
                                           biz_days_total, biz_days_elapsed)
        source = "salesforce"
    else:
        # ── FALLBACK: Use static forecast_data.py ─────────────────────────
        reps = _process_from_static_data(year, month_num,
                                          biz_days_total, biz_days_elapsed)
        source = "static"

    logger.info("Forecast source: %s, %d reps", source, len(reps))

    # ── Sort by variance_pct descending (best performers first) ───────────
    reps.sort(key=lambda r: r["variance_pct"], reverse=True)

    # ── Team-level aggregates ─────────────────────────────────────────────
    team_budget = sum(r["budget"] for r in reps)
    team_mtd = sum(r["mtd_actual"] for r in reps)
    team_projected = sum(r["projected"] for r in reps)
    team_variance_pct = round((team_projected / team_budget - 1) * 100, 1) if team_budget > 0 else 0.0

    return {
        "month_name": month_name,
        "month_num": month_num,
        "year": year,
        "biz_days_elapsed": biz_days_elapsed,
        "biz_days_total": biz_days_total,
        "last_updated": current_date.isoformat(),
        "reps": reps,
        "team_budget": team_budget,
        "team_mtd": team_mtd,
        "team_projected": team_projected,
        "team_variance_pct": team_variance_pct,
    }


def _process_from_quota_report(quota_rows, year, month_num,
                                biz_days_total, biz_days_elapsed) -> list:
    """
    Build per-rep forecast data from live Salesforce Monthly Quota report.

    Report columns used:
        User, Funded Dollars Quota, Funded Dollars,
        Funded Dollars Difference, Funding Progress, Funding Projected
    """
    # Build lookup: rep name → row data
    # The report uses _label_ prefix for display values in SUMMARY format,
    # but as a TABULAR report the labels are direct column names.
    osr_names_lower = {name.lower(): name for name in OSR_ROSTER}
    territory_by_osr = {v: k for k, v in TERRITORY_MAP.items()}

    reps = []
    for row in quota_rows:
        # Try both raw and _label_ versions
        rep_name = (row.get("_label_User") or row.get("User") or "").strip()

        # Match against OSR roster (case-insensitive)
        roster_name = osr_names_lower.get(rep_name.lower())
        if not roster_name:
            continue

        # Parse numeric values (handle None/NaN)
        budget = _safe_float(row.get("Funded Dollars Quota") or row.get("_label_Funded Dollars Quota"))
        mtd_actual = _safe_float(row.get("Funded Dollars") or row.get("_label_Funded Dollars"))

        if budget is None or budget == 0:
            continue  # Skip reps with no quota assigned

        if mtd_actual is None:
            mtd_actual = 0

        territory = territory_by_osr.get(roster_name, "")

        # Project end-of-month based on current pace
        projected = round(mtd_actual * (biz_days_total / biz_days_elapsed))

        # Variance vs budget
        variance_pct = round((projected / budget - 1) * 100, 1) if budget > 0 else 0.0

        reps.append({
            "name": roster_name,
            "territory": territory,
            "budget": round(budget, 2),
            "mtd_actual": round(mtd_actual, 2),
            "projected": projected,
            "variance_pct": variance_pct,
            "on_track": projected >= budget,
        })

    return reps


def _process_from_static_data(year, month_num, biz_days_total, biz_days_elapsed) -> list:
    """Fallback: build forecast from static forecast_data.py."""
    try:
        from ..forecast_data import TERRITORY_BUDGETS, TERRITORY_ACTUALS
    except ImportError:
        logger.warning("No forecast_data.py found and no quota report data. Returning empty forecast.")
        return []

    reps = []
    for territory, osr_name in TERRITORY_MAP.items():
        budgets = TERRITORY_BUDGETS.get(territory)
        actuals = TERRITORY_ACTUALS.get(territory)

        if not budgets or not actuals:
            continue

        current_month_idx = month_num - 1
        budget = budgets[current_month_idx]
        mtd_actual = actuals[current_month_idx] if len(actuals) >= month_num else 0

        projected = round(mtd_actual * (biz_days_total / biz_days_elapsed))
        variance_pct = round((projected / budget - 1) * 100, 1) if budget > 0 else 0.0

        reps.append({
            "name": osr_name,
            "territory": territory,
            "budget": budget,
            "mtd_actual": mtd_actual,
            "projected": projected,
            "variance_pct": variance_pct,
            "on_track": projected >= budget,
        })

    return reps


def _safe_float(val) -> float | None:
    """Safely parse a value to float, returning None for unparseable values."""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (ValueError, TypeError):
        return None
