"""
Quarterly enrollment compliance processor.

Transforms credited enrollment counts into the q1Data array structure
used by q1-enrollment.html.

Rules: 30 enrollments per quarter, no single month below 10 floor,
quarterly true-up if total hits 30.
"""

import logging
from collections import Counter
from datetime import date
import calendar

from ..config import COLUMN_LABELS, MONTH_ABBREV, MONTHLY_FLOOR, QUARTERLY_TARGET

logger = logging.getLogger(__name__)


def process(monthly_credited: dict[str, list[dict]], quarter_months: list[int],
            year: int) -> dict:
    """
    Process credited enrollment data into quarterly compliance structure.

    Args:
        monthly_credited: Dict mapping month abbreviation ("jan", "feb", "mar")
                         to credited enrollment rows for that month
        quarter_months: List of month numbers in the quarter, e.g., [1, 2, 3]
        year: Year of the quarter

    Returns:
        Dict with q1Data array and KPI values
    """
    today = date.today()

    # ── Count enrollments per OSR per month ──────────────────────────────
    osr_monthly = {}  # osr_name -> {month_abbrev: count}

    for month_num in quarter_months:
        abbrev = MONTH_ABBREV[month_num]
        rows = monthly_credited.get(abbrev, [])

        osr_counts = Counter()
        for row in rows:
            osr = _get(row, "osr_credit", "")
            if osr:
                osr_counts[osr] += 1

        for osr, count in osr_counts.items():
            if osr not in osr_monthly:
                osr_monthly[osr] = {}
            osr_monthly[osr][abbrev] = count

    # ── Build q1Data array ───────────────────────────────────────────────
    q1_data = []

    for osr, monthly_counts in sorted(osr_monthly.items()):
        entry = {"n": osr}
        total = 0

        for month_num in quarter_months:
            abbrev = MONTH_ABBREV[month_num]
            count = monthly_counts.get(abbrev, 0)

            # If this month is current or future, show 0 (in progress)
            is_current_or_future = (year > today.year or
                                    (year == today.year and month_num >= today.month))

            entry[abbrev] = count
            total += count

        entry["q1"] = total
        entry["need"] = max(0, QUARTERLY_TARGET - total)

        # Check monthly floor compliance and in-progress status
        for month_num in quarter_months:
            abbrev = MONTH_ABBREV[month_num]
            count = monthly_counts.get(abbrev, 0)
            # Only flag completed months
            is_completed = (year < today.year or
                           (year == today.year and month_num < today.month))
            is_current_or_future = not is_completed
            entry[f"{abbrev}Ok"] = count >= MONTHLY_FLOOR if is_completed else True
            entry[f"{abbrev}Prog"] = is_current_or_future

        q1_data.append(entry)

    # Sort by Q1 total descending
    q1_data.sort(key=lambda x: x["q1"], reverse=True)

    # ── KPI calculations ─────────────────────────────────────────────────
    total_q1_enrollments = sum(e["q1"] for e in q1_data)
    reps_at_target = sum(1 for e in q1_data if e["q1"] >= QUARTERLY_TARGET)
    total_reps = len(q1_data)

    # Count months under floor (only for completed months)
    months_under_10 = 0
    for e in q1_data:
        for month_num in quarter_months:
            abbrev = MONTH_ABBREV[month_num]
            is_completed = (year < today.year or
                           (year == today.year and month_num < today.month))
            if is_completed and e.get(abbrev, 0) < MONTHLY_FLOOR:
                months_under_10 += 1

    # Days remaining in current month
    if today.year == year and today.month in quarter_months:
        _, days_in_month = calendar.monthrange(today.year, today.month)
        days_remaining = days_in_month - today.day
    else:
        days_remaining = 0

    current_month_name = calendar.month_name[today.month] if today.month in quarter_months else ""

    logger.info(
        "Q%d %d: %d total enrollments, %d/%d reps at target",
        (quarter_months[0] - 1) // 3 + 1, year,
        total_q1_enrollments, reps_at_target, total_reps
    )

    return {
        "q1Data": q1_data,
        "kpi_total_enrollments": total_q1_enrollments,
        "kpi_at_target": f"{reps_at_target} / {total_reps}",
        "kpi_months_under_10": months_under_10,
        "kpi_days_remaining": f"{days_remaining} days",
        "kpi_current_month": current_month_name,
        "quarter_months": quarter_months,
        "year": year,
    }


def _get(row: dict, col_key: str, default: str = "") -> str:
    label = COLUMN_LABELS.get(col_key, col_key)
    return row.get(label, default)
