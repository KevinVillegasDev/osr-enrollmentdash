"""
Forecast / pacing data processor.

Takes territory-level budget targets and actuals from forecast_data,
maps territories to OSRs via config.TERRITORY_MAP, and produces
per-rep forecast projections including MTD pacing, end-of-month projection,
and year-to-date variance.

Inputs: TERRITORY_BUDGETS, TERRITORY_ACTUALS (from automation.forecast_data)
Outputs: Dict with per-rep forecast data and team-level aggregates.
"""

import logging
from datetime import datetime, date, timedelta

from ..config import TERRITORY_MAP, MONTH_NAMES
from ..forecast_data import TERRITORY_BUDGETS, TERRITORY_ACTUALS, LAST_UPDATED, MTD_MONTH

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


def process_forecast(current_date=None) -> dict:
    """
    Process budget targets and actuals into per-rep forecast data.

    Args:
        current_date: Override for today's date (datetime or date). Defaults to now.

    Returns:
        Dict with month info, per-rep forecasts (sorted by variance descending),
        and team-level aggregates.
    """
    if current_date is None:
        current_date = datetime.now()
    if isinstance(current_date, datetime):
        current_date = current_date.date()

    year = current_date.year
    month_num = MTD_MONTH
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

    for territory, osr_name in TERRITORY_MAP.items():
        budgets = TERRITORY_BUDGETS.get(territory)
        actuals = TERRITORY_ACTUALS.get(territory)

        if not budgets:
            logger.warning("No budget data for territory %s (%s), skipping.", territory, osr_name)
            continue
        if not actuals:
            logger.warning("No actuals data for territory %s (%s), skipping.", territory, osr_name)
            continue

        # ── Current month (MTD) ───────────────────────────────────────────
        current_month_idx = month_num - 1  # 0-based index into budgets list
        budget = budgets[current_month_idx]
        mtd_actual = actuals[current_month_idx] if len(actuals) >= month_num else 0

        # Project end-of-month based on current pace
        projected = round(mtd_actual * (biz_days_total / biz_days_elapsed))

        # Variance vs budget (percentage)
        if budget > 0:
            variance_pct = round((projected / budget - 1) * 100, 1)
        else:
            variance_pct = 0.0

        # ── Monthly history (completed months) ────────────────────────────
        monthly_history = []
        for m in range(1, month_num):  # Months before MTD_MONTH are finalized
            m_idx = m - 1
            m_actual = actuals[m_idx] if len(actuals) > m_idx else 0
            m_budget = budgets[m_idx]
            m_var = round((m_actual / m_budget - 1) * 100, 1) if m_budget > 0 else 0.0
            m_abbrev = MONTH_NAMES[m][:3]
            monthly_history.append({
                "month": m_abbrev,
                "actual": m_actual,
                "budget": m_budget,
                "var_pct": m_var,
            })

        # ── Year-to-date ──────────────────────────────────────────────────
        # YTD actual = sum of completed months + current MTD
        completed_actuals = sum(actuals[i] for i in range(month_num - 1) if i < len(actuals))
        ytd_actual = completed_actuals + mtd_actual

        # YTD projected = sum of completed months + current month projected
        ytd_projected = completed_actuals + projected

        # YTD budget = sum of budgets through current month
        ytd_budget = sum(budgets[i] for i in range(month_num))

        ytd_variance_pct = round((ytd_projected / ytd_budget - 1) * 100, 1) if ytd_budget > 0 else 0.0

        reps.append({
            "name": osr_name,
            "territory": territory,
            "budget": budget,
            "mtd_actual": mtd_actual,
            "projected": projected,
            "variance_pct": variance_pct,
            "ytd_budget": ytd_budget,
            "ytd_actual": ytd_actual,
            "ytd_projected": ytd_projected,
            "ytd_variance_pct": ytd_variance_pct,
            "monthly_history": monthly_history,
            "on_track": projected >= budget,
        })

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
        "last_updated": LAST_UPDATED,
        "reps": reps,
        "team_budget": team_budget,
        "team_mtd": team_mtd,
        "team_projected": team_projected,
        "team_variance_pct": team_variance_pct,
    }
