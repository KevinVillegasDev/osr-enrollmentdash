"""
Analytics & Insights processor.

Aggregates cross-month data from monthly dashboard results, cohort tracking,
and Q1 enrollment data to produce the data structure for analytics.html.

Outputs: monthlyKPIs, repTrends, dailyPace, marketTrends, cohortReps,
funnelData, and metadata (bizDaysLeft, month labels).
"""

import calendar
import json
import logging
import os
import re
from collections import defaultdict
from datetime import date

from ..config import (
    MONTH_NAMES, MONTH_ABBREV, PROJECT_ROOT,
    month_filepath, QUARTERLY_TARGET,
)

logger = logging.getLogger(__name__)


def process(monthly_results: dict, q1_data: dict, cohorts: dict,
            current_month: int, current_year: int) -> dict:
    """
    Process cross-month analytics data for analytics.html.

    Args:
        monthly_results: Dict of month_key → monthly_dashboard output or HTML extract.
                         Keys like "jan-2026", "feb-2026", "mar-2026".
        q1_data: Output from q1_enrollment.process()
        cohorts: Dict of var_name → cohort array from cohort_tracking.process_cohort()
                 e.g., {"febCohort": [...], "janCohort": [...]}
        current_month: Current month number (1-12)
        current_year: Current year

    Returns:
        Dict with all data variables for analytics.html
    """
    today = date.today()
    prev_month = current_month - 1 if current_month > 1 else 12
    prev_year = current_year if current_month > 1 else current_year - 1

    # ── monthlyKPIs: per-month summary array ──────────────────────────
    monthly_kpis = _build_monthly_kpis(monthly_results, current_month, current_year)

    # ── repTrends: per-rep per-month enrollment counts ────────────────
    rep_trends = _build_rep_trends(q1_data, current_month, current_year)

    # ── Daily pace data ───────────────────────────────────────────────
    cur_key = f"{MONTH_ABBREV[current_month]}-{current_year}"
    cur_data = monthly_results.get(cur_key, {})
    daily_pace_current = cur_data.get("dailyTrend", [])

    prev_key = f"{MONTH_ABBREV[prev_month]}-{prev_year}"
    prev_data = monthly_results.get(prev_key, {})
    daily_pace_previous = prev_data.get("dailyTrend", [])

    # If no daily trend from processed results, extract from HTML
    if not daily_pace_previous:
        daily_pace_previous = _extract_daily_trend_from_html(prev_month, prev_year)

    biz_days_left = _calc_biz_days_left(today, current_month, current_year)
    biz_days_elapsed = _calc_biz_days_elapsed(today, current_month, current_year)

    # ── Market trends: per-state per-month ────────────────────────────
    market_trends = _build_market_trends(monthly_results, current_month, current_year)

    # ── Cohort reps (simplified for analytics display) ────────────────
    # Active cohort comes from pipeline processing; baseline/completed cohorts
    # are extracted from cohort-tracking.html since they aren't re-processed.
    cohort_reps_data = _build_cohort_reps(cohorts, current_month, current_year)
    _fill_missing_cohorts(cohort_reps_data, current_month, current_year)

    # ── Funnel data from current month ────────────────────────────────
    funnel_data = _build_funnel(cur_data)

    logger.info(
        "Analytics: %d months of KPIs, %d reps, %d market states, %d cohorts",
        len(monthly_kpis), len(rep_trends), len(market_trends),
        len(cohort_reps_data),
    )

    return {
        "monthlyKPIs": monthly_kpis,
        "repTrends": rep_trends,
        "dailyPaceCurrent": daily_pace_current,
        "dailyPacePrevious": daily_pace_previous,
        "marketTrends": market_trends,
        "cohortReps": cohort_reps_data,  # dict of var_name → simplified array
        "funnelData": funnel_data,
        "bizDaysLeft": biz_days_left,
        "bizDaysElapsed": biz_days_elapsed,
        "currentMonthLabel": MONTH_NAMES[current_month],
        "previousMonthLabel": MONTH_NAMES[prev_month],
    }


# ── Builder functions ────────────────────────────────────────────────────────

def _build_monthly_kpis(monthly_results: dict, current_month: int,
                         current_year: int) -> list:
    """Build monthlyKPIs array for all months with data."""
    kpis = []

    for m in range(1, current_month + 1):
        key = f"{MONTH_ABBREV[m]}-{current_year}"
        data = monthly_results.get(key)
        if not data:
            continue

        # Extract funded raw amount
        funded_raw = _extract_funded_raw(data)

        # Product mix (LTO vs RC)
        lto, rc = 0, 0
        if "osr_product_mix" in data:
            lto, rc = data["osr_product_mix"]

        entry = {
            "month": f"{MONTH_NAMES[m][:3]} {current_year}",
            "key": MONTH_ABBREV[m],
            "total": data.get("kpi_total", 0),
            "credited": data.get("kpi_osr", 0),
            "funded": round(funded_raw),
            "fundedApps": data.get("kpi_funded_apps", 0),
            "totalApps": data.get("kpi_total_apps", 0),
            "convRate": data.get("kpi_conversion", 0),
            "avgTicket": _parse_avg_ticket(data.get("kpi_avg_ticket", "0")),
            "lto": lto,
            "rc": rc,
        }
        kpis.append(entry)

    return kpis


def _build_rep_trends(q1_data: dict, current_month: int,
                       current_year: int) -> list:
    """Build repTrends array from Q1 enrollment data."""
    if not q1_data or "q1Data" not in q1_data:
        return []

    quarter_months = q1_data.get("quarter_months", [1, 2, 3])
    trends = []

    for rep in q1_data["q1Data"]:
        entry = {"n": rep["n"]}
        for m in quarter_months:
            abbrev = MONTH_ABBREV[m]
            entry[abbrev] = rep.get(abbrev, 0)
        entry["q1"] = rep.get("q1", 0)
        entry["target"] = QUARTERLY_TARGET
        trends.append(entry)

    # Sort by Q1 total descending
    trends.sort(key=lambda x: x["q1"], reverse=True)
    return trends


def _build_market_trends(monthly_results: dict, current_month: int,
                          current_year: int) -> list:
    """Build marketTrends array: per-state counts across all months."""
    state_data = defaultdict(lambda: defaultdict(int))

    for m in range(1, current_month + 1):
        key = f"{MONTH_ABBREV[m]}-{current_year}"
        data = monthly_results.get(key)
        if not data:
            continue

        market_data = data.get("marketData", [])
        abbrev = MONTH_ABBREV[m]

        for item in market_data:
            state = item.get("n", "")
            count = item.get("v", 0)
            if state:
                # Normalize: full names → abbreviations
                state = _normalize_state(state)
                state_data[state][abbrev] += count

    # Convert to array format, sorted by total descending
    trends = []
    for state, months in state_data.items():
        entry = {"state": state}
        total = 0
        for m in range(1, current_month + 1):
            abbrev = MONTH_ABBREV[m]
            val = months.get(abbrev, 0)
            entry[abbrev] = val
            total += val
        entry["_total"] = total
        trends.append(entry)

    trends.sort(key=lambda x: x["_total"], reverse=True)

    # Remove internal sort key and take top states
    for t in trends:
        del t["_total"]

    return trends[:10]


def _build_cohort_reps(cohorts: dict, current_month: int,
                        current_year: int) -> dict:
    """
    Build simplified cohort rep arrays for analytics display.

    Input: {"febCohort": [full cohort tracking entries], ...}
    Output: {"febCohortReps": [{n, m, p, f}, ...], "janCohortReps": [...]}
    """
    result = {}

    for var_name, cohort_array in cohorts.items():
        # Transform var name: "febCohort" → "febCohortReps"
        reps_var = var_name + "Reps"
        simplified = []

        for rep in cohort_array:
            simplified.append({
                "n": rep.get("n", ""),
                "m": rep.get("m", 0),
                "p": rep.get("p", 0),
                "f": round(rep.get("f", 0)),
            })

        # Sort by funded descending
        simplified.sort(key=lambda x: x["f"], reverse=True)
        result[reps_var] = simplified

    return result


def _fill_missing_cohorts(cohort_reps: dict, current_month: int,
                           current_year: int) -> None:
    """
    Fill in cohort reps for months not in the pipeline's active cohorts.

    Extracts simplified cohort data from cohort-tracking.html for baseline
    and completed cohorts that aren't re-processed by the pipeline each run.
    """
    # Determine which cohort months should exist (Jan 2026 through prev month)
    for m in range(1, current_month):
        var_name = f"{MONTH_ABBREV[m]}CohortReps"
        if var_name in cohort_reps:
            continue  # Already have this from pipeline

        # Try to extract from cohort-tracking.html
        cohort_var = f"{MONTH_ABBREV[m]}Cohort"
        reps = _extract_cohort_from_html(cohort_var)
        if reps:
            cohort_reps[var_name] = reps
            logger.info("Extracted %s from cohort-tracking.html (%d reps)",
                         var_name, len(reps))


def _extract_cohort_from_html(var_name: str) -> list:
    """Extract and simplify a cohort array from cohort-tracking.html."""
    filepath = os.path.join(PROJECT_ROOT, "cohort-tracking.html")
    if not os.path.exists(filepath):
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()

        pattern = rf'var {var_name}\s*=\s*(\[.*?\]);'
        match = re.search(pattern, html, re.DOTALL)
        if not match:
            return []

        js_str = match.group(1)
        json_str = re.sub(r'([{,])\s*([a-zA-Z_]\w*)\s*:', r'\1"\2":', js_str)
        json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
        json_str = json_str.replace("\\'", "'")

        cohort = json.loads(json_str)

        # Simplify to {n, m, p, f} format
        return sorted(
            [{"n": r.get("n", ""), "m": r.get("m", 0),
              "p": r.get("p", 0), "f": round(r.get("f", 0))}
             for r in cohort],
            key=lambda x: x["f"], reverse=True,
        )
    except Exception as e:
        logger.warning("Failed to extract %s from HTML: %s", var_name, e)
        return []


def _build_funnel(current_month_data: dict) -> list:
    """Build funnelData from current month's dashboard data."""
    if not current_month_data:
        return []

    kpi_total = current_month_data.get("kpi_total", 0)
    kpi_osr = current_month_data.get("kpi_osr", 0)
    kpi_active = current_month_data.get("kpi_active_merchants", 0)
    kpi_funded_apps = current_month_data.get("kpi_funded_apps", 0)
    kpi_producing = current_month_data.get("kpi_producing_merchants", 0)

    return [
        {"l": "Total Enrolled (All Channels)", "v": kpi_total, "c": "#5B9BFF"},
        {"l": "OSR-Credited", "v": kpi_osr, "c": "#A78BFA"},
        {"l": "Merchants with Applications", "v": kpi_active, "c": "#FBBF24"},
        {"l": "Funded Applications", "v": kpi_funded_apps, "c": "#2DD4A0"},
        {"l": "Producing Merchants (>$0)", "v": kpi_producing, "c": "#10B981"},
    ]


# ── Helpers ──────────────────────────────────────────────────────────────────

_STATE_ABBREV = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}


def _normalize_state(state: str) -> str:
    """Normalize state name to 2-letter abbreviation."""
    s = state.strip()
    if len(s) <= 2:
        return s.upper()
    return _STATE_ABBREV.get(s.lower(), s)


def _extract_funded_raw(data: dict) -> float:
    """Extract raw funded dollar amount from monthly dashboard data."""
    # Full monthly_dashboard output has topProducers with individual amounts
    # but also kpi_funded_display like "$33,126" or kpi_funded_short like "$33K"
    display = data.get("kpi_funded_display", "") or data.get("kpi_funded_short", "")
    if not display:
        # Try synthetic topProducers (HTML fallback stores total there)
        top = data.get("topProducers", [])
        if top and isinstance(top[0], dict):
            return sum(p.get("f", 0) for p in top)
        return 0.0

    return _parse_dollar_amount(display)


def _parse_dollar_amount(s: str) -> float:
    """Parse a dollar display string like '$33,126' or '$167K' to float."""
    s = s.strip().lstrip("$").replace(",", "")
    if s.upper().endswith("M"):
        return float(s[:-1]) * 1_000_000
    elif s.upper().endswith("K"):
        return float(s[:-1]) * 1_000
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _parse_avg_ticket(val) -> int:
    """Parse avg ticket value — may be '$1,633' string or int."""
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip().lstrip("$").replace(",", "")
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _calc_biz_days_left(today: date, month: int, year: int) -> int:
    """Calculate business days remaining in the month."""
    _, days_in_month = calendar.monthrange(year, month)
    count = 0
    for d in range(today.day + 1, days_in_month + 1):
        dt = date(year, month, d)
        if dt.weekday() < 5:  # Mon-Fri
            count += 1
    return count


def _calc_biz_days_elapsed(today: date, month: int, year: int) -> int:
    """Calculate business days elapsed in the month (including today)."""
    count = 0
    for d in range(1, today.day + 1):
        dt = date(year, month, d)
        if dt.weekday() < 5:  # Mon-Fri
            count += 1
    return count


def _extract_daily_trend_from_html(month: int, year: int) -> list:
    """Extract dailyTrend JS variable from a monthly dashboard HTML file."""
    filepath = month_filepath(month, year)
    if not os.path.exists(filepath):
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()

        pattern = r'var dailyTrend\s*=\s*(\[.*?\]);'
        m = re.search(pattern, html, re.DOTALL)
        if not m:
            return []

        js_str = m.group(1)
        # Convert JS object literal to JSON
        json_str = re.sub(r'([{,])\s*([a-zA-Z_]\w*)\s*:', r'\1"\2":', js_str)
        json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

        return json.loads(json_str)
    except Exception as e:
        logger.warning("Failed to extract dailyTrend from %s %d HTML: %s",
                        MONTH_NAMES[month], year, e)
        return []
