"""
Index page (landing page) data processor.

Aggregates data from all other processors to compute the YTD summary,
commission tracking card, Q1 enrollment card, field activity card,
and per-month dashboard card values for index.html.
"""

import logging

from ..config import MONTH_ABBREV, OSR_ROSTER, ISR_ROSTER
from .forecast import process_forecast

logger = logging.getLogger(__name__)

# Reverse lookup: month abbreviation → month number for sorting
_ABBREV_TO_NUM = {v: k for k, v in MONTH_ABBREV.items()}


def process(monthly_results: dict[str, dict],
            cohort_kpis: dict,
            q1_result: dict,
            field_result: dict,
            current_month_key: str = "",
            genesys_data: list = None,
            quota_rows: list = None) -> dict:
    """
    Aggregate all processor outputs into index.html display values.

    Args:
        monthly_results: Dict mapping month filenames to their monthly_dashboard.process() results.
                        e.g., {"jan-2026": {...}, "feb-2026": {...}}
        cohort_kpis: Dict with cohort tracking KPIs from cohort_tracking.compute_cohort_kpis()
                    Keys: active_cohort, baseline_cohort (each with total_funded_display, etc.)
        q1_result: Output from q1_enrollment.process()
        field_result: Output from field_activity.process()
        genesys_data: List of dicts from Genesys Cloud (agent talk time data)
        quota_rows: Optional list of parsed rows from Report 6 (Monthly Quota)

    Returns:
        Dict with all values needed to update index.html
    """
    # ── YTD Summary ──────────────────────────────────────────────────────
    ytd_total_enrollments = 0
    ytd_osr_credited = 0
    ytd_funded_volume = 0.0
    months_tracked = len(monthly_results)

    month_cards = []

    for key, data in sorted(monthly_results.items(), key=_month_sort_key):
        ytd_total_enrollments += data.get("kpi_total", 0)
        ytd_osr_credited += data.get("kpi_osr", 0)
        # Sum funded from the funnel's producing merchants total
        # or use the formatted value
        funded_display = data.get("kpi_funded_display", "$0")
        funded_short = data.get("kpi_funded_short", "$0")

        # Try to extract numeric funded value
        funded_num = 0
        for fi_item in data.get("fi", []):
            pass  # funnel items don't have total funded
        # Use the total from topProducers instead
        top_prods = data.get("topProducers", [])
        funded_num = sum(p["f"] for p in top_prods)
        ytd_funded_volume += funded_num

        # Per-month card data
        top_rep = data.get("repCredits", [{}])[0] if data.get("repCredits") else {}
        top_market = data.get("marketData", [{}])[0] if data.get("marketData") else {}

        month_cards.append({
            "key": key,
            "month_name": data.get("month_name", ""),
            "year": data.get("year", 2026),
            "kpi_total": data.get("kpi_total", 0),
            "kpi_osr": data.get("kpi_osr", 0),
            "kpi_funded_short": funded_short,
            "kpi_conversion": f"{data.get('kpi_conversion', 0)}%",
            "top_rep_name": top_rep.get("n", "N/A"),
            "top_rep_count": top_rep.get("v", 0),
            "top_market_name": top_market.get("n", "N/A"),
            "top_market_count": top_market.get("v", 0),
        })

    ytd_credit_pct = round(ytd_osr_credited / ytd_total_enrollments * 100, 1) if ytd_total_enrollments > 0 else 0

    # ── Format YTD funded volume ─────────────────────────────────────────
    if ytd_funded_volume >= 1_000_000:
        ytd_funded_display = f"${ytd_funded_volume/1_000_000:.1f}M"
    elif ytd_funded_volume >= 1_000:
        ytd_funded_display = f"${ytd_funded_volume/1_000:.0f}K"
    else:
        ytd_funded_display = f"${int(ytd_funded_volume)}"

    logger.info(
        "Index: YTD %d enrollments, %d credited, %s funded, %d months",
        ytd_total_enrollments, ytd_osr_credited, ytd_funded_display, months_tracked
    )

    # ── Rep Scorecard ─────────────────────────────────────────────────────
    # Merge field activity (stops/day), enrollments, and M0 funded per rep
    current_data = monthly_results.get(current_month_key, {}) if current_month_key else {}
    scorecard = _build_rep_scorecard(field_result, current_data)

    # Determine current month label for scorecard subtitle
    scorecard_month = current_data.get("month_name", "")
    scorecard_year = current_data.get("year", 2026)

    # ── Production Forecast ────────────────────────────────────────────
    try:
        forecast_data = process_forecast(quota_rows=quota_rows)
        logger.info("Forecast: %d reps, team variance %.1f%%",
                     len(forecast_data.get("reps", [])),
                     forecast_data.get("team_variance_pct", 0))
    except Exception as e:
        logger.warning("Forecast processing failed: %s", e)
        forecast_data = {}

    return {
        # YTD Summary
        "ytd_total_enrollments": ytd_total_enrollments,
        "ytd_osr_credited": ytd_osr_credited,
        "ytd_credit_pct": f"{ytd_credit_pct}% of total",
        "ytd_funded_display": ytd_funded_display,
        "ytd_funded_sub": "Month 0 across all months",
        "ytd_months_tracked": months_tracked,
        "ytd_months_sub": _months_tracked_sub(monthly_results),

        # Commission tracking card
        "cohort": cohort_kpis,

        # Q1 enrollment compliance card
        "q1_total": q1_result.get("kpi_total_enrollments", 0),
        "q1_at_target": q1_result.get("kpi_at_target", "0 / 0"),
        "q1_months_under_10": q1_result.get("kpi_months_under_10", 0),
        "q1_days_remaining": q1_result.get("kpi_days_remaining", "0 days"),
        "quarter_num": (q1_result.get("quarter_months", [1])[0] - 1) // 3 + 1,
        "quarter_filename": f"q{(q1_result.get('quarter_months', [1])[0] - 1) // 3 + 1}-enrollment.html",
        "quarter_current_month": q1_result.get("kpi_current_month", ""),

        # Field activity card
        "field_total_stops": field_result.get("kpi_total_stops", 0),
        "field_existing": field_result.get("kpi_existing", 0),
        "field_prospect": field_result.get("kpi_prospect", 0),
        "field_reps_active": field_result.get("kpi_reps_active", 0),
        "field_avg_per_day": field_result.get("kpi_avg_per_day", 0),
        "field_month_range": field_result.get("kpi_month_range", "N/A"),

        # Per-month dashboard cards
        "month_cards": month_cards,

        # Rep Scorecard
        "rep_scorecard": scorecard,
        "scorecard_month": scorecard_month,
        "scorecard_year": scorecard_year,

        # ISR Scorecard (Genesys talk time)
        "isr_scorecard": _build_isr_scorecard(genesys_data or []),

        # Production Forecast
        "forecast": forecast_data,
    }


def _build_rep_scorecard(field_result: dict, current_month_data: dict) -> list[dict]:
    """
    Build per-rep scorecard combining field activity, enrollments, and M0 funded.

    Returns list of dicts sorted by enrollments descending:
        [{name, stops_per_day, enrollments, funded}, ...]
    """
    # 1. Per-rep avg stops/day, prospect/existing stops, avg hours from field activity
    rep_stops = {}
    rep_prospect_stops = {}
    rep_existing_stops = {}
    rep_total_stops = {}
    rep_avg_hours = {}
    for rep_act in field_result.get("repActivity", []):
        name = rep_act.get("n", "")
        total = rep_act.get("t", 0)
        daily = rep_act.get("daily", {})
        active_days = len(daily)
        avg = round(total / active_days, 1) if active_days > 0 else 0
        rep_stops[name] = avg
        rep_prospect_stops[name] = rep_act.get("pr", 0)
        rep_existing_stops[name] = rep_act.get("ex", 0)
        rep_total_stops[name] = total
        rep_avg_hours[name] = rep_act.get("avg_hours", 0)

    # 2. Per-rep enrollment counts from current month repCredits
    rep_enrollments = {}
    for rc in current_month_data.get("repCredits", []):
        rep_enrollments[rc["n"]] = rc["v"]

    # 3. Per-rep M0 funded volume from current month repMerchants
    rep_funded = {}
    for osr, merchants in current_month_data.get("repMerchants", {}).items():
        rep_funded[osr] = sum(m.get("f", 0) for m in merchants)

    # Merge across all OSR roster reps
    scorecard = []
    for name in OSR_ROSTER:
        prospects = rep_prospect_stops.get(name, 0)
        existing = rep_existing_stops.get(name, 0)
        total = rep_total_stops.get(name, 0)
        enrollments = rep_enrollments.get(name, 0)
        # Prospect stops per enrollment — lower = more efficient
        ratio = round(prospects / enrollments, 1) if enrollments > 0 else None
        # Prospect % of total stops — hunting vs farming indicator
        prospect_pct = round(prospects / total * 100) if total > 0 else None
        scorecard.append({
            "name": name,
            "stops_per_day": rep_stops.get(name, 0),
            "avg_hours": rep_avg_hours.get(name, 0),
            "prospect_stops": prospects,
            "existing_stops": existing,
            "total_stops": total,
            "prospect_pct": prospect_pct,
            "enrollments": enrollments,
            "stops_per_enroll": ratio,
            "funded": round(rep_funded.get(name, 0), 2),
        })

    # Sort by enrollments descending, then by funded descending
    scorecard.sort(key=lambda r: (r["enrollments"], r["funded"]), reverse=True)

    logger.info("Scorecard: %d reps, %d with stops, %d with enrollments",
                len(scorecard),
                sum(1 for r in scorecard if r["stops_per_day"] > 0),
                sum(1 for r in scorecard if r["enrollments"] > 0))

    return scorecard


def _months_tracked_sub(monthly_results: dict) -> str:
    """Generate the subtitle for months tracked, e.g., 'January & February 2026'."""
    if not monthly_results:
        return "No months tracked"

    month_names = []
    year = None
    for key, data in sorted(monthly_results.items(), key=_month_sort_key):
        month_names.append(data.get("month_name", ""))
        year = data.get("year", 2026)

    if len(month_names) == 1:
        return f"{month_names[0]} {year}"
    elif len(month_names) == 2:
        return f"{month_names[0]} & {month_names[1]} {year}"
    else:
        return ", ".join(month_names[:-1]) + f" & {month_names[-1]} {year}"


def _month_sort_key(item: tuple) -> int:
    """Sort key for monthly_results items — chronological order by month number."""
    key = item[0]  # e.g., "feb-2026"
    abbrev = key.split("-")[0]
    return _ABBREV_TO_NUM.get(abbrev, 0)


def _build_isr_scorecard(genesys_data: list) -> list[dict]:
    """
    Filter Genesys talk time data to ISR_ROSTER reps only.

    Returns list of dicts sorted by talk_seconds descending:
        [{name, talk_seconds, talk_display, calls}, ...]
    """
    if not genesys_data:
        return []

    # Filter to ISR roster only (case-insensitive matching)
    isr_names_lower = {name.lower() for name in ISR_ROSTER}
    isr_data = [
        agent for agent in genesys_data
        if agent.get("name", "").lower() in isr_names_lower
    ]

    # Sort by talk time descending
    isr_data.sort(key=lambda a: a.get("talk_seconds", 0), reverse=True)

    logger.info("ISR scorecard: %d/%d roster reps found in Genesys data",
                len(isr_data), len(ISR_ROSTER))

    return isr_data
