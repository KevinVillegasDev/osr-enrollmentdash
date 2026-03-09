"""
Index page (landing page) data processor.

Aggregates data from all other processors to compute the YTD summary,
commission tracking card, Q1 enrollment card, field activity card,
and per-month dashboard card values for index.html.
"""

import logging

from ..config import MONTH_ABBREV

logger = logging.getLogger(__name__)

# Reverse lookup: month abbreviation → month number for sorting
_ABBREV_TO_NUM = {v: k for k, v in MONTH_ABBREV.items()}


def process(monthly_results: dict[str, dict],
            cohort_kpis: dict,
            q1_result: dict,
            field_result: dict) -> dict:
    """
    Aggregate all processor outputs into index.html display values.

    Args:
        monthly_results: Dict mapping month filenames to their monthly_dashboard.process() results.
                        e.g., {"jan-2026": {...}, "feb-2026": {...}}
        cohort_kpis: Dict with cohort tracking KPIs from cohort_tracking.compute_cohort_kpis()
                    Keys: active_cohort, baseline_cohort (each with total_funded_display, etc.)
        q1_result: Output from q1_enrollment.process()
        field_result: Output from field_activity.process()

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
    }


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
