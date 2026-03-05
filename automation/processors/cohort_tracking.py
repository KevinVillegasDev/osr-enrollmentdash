"""
Cohort tracking data processor.

Transforms Salesforce report data into the JS cohort array structures
used by cohort-tracking.html.

Each cohort = one month's enrollees tracked across M0, M1, and optionally M2.
"""

import logging
from collections import defaultdict
from datetime import date

from ..config import COLUMN_LABELS, MONTH_ABBREV, MONTH_NAMES, COHORT_TARGET_M1, COHORT_TARGET_M2

logger = logging.getLogger(__name__)


def process_cohort(credited_enrollments: list[dict],
                   monthly_activity: dict[str, list[dict]],
                   enrollment_month: int,
                   enrollment_year: int) -> list[dict]:
    """
    Process a single cohort (one enrollment month) into the JS data structure.

    Args:
        credited_enrollments: Rows from Report 2 for the enrollment month
        monthly_activity: Dict mapping month abbreviation (e.g., "jan", "feb") to
                         rows of activity data for that month.
                         Keys should be the abbreviated month names that had activity.
        enrollment_month: The enrollment month (1-12)
        enrollment_year: The enrollment year

    Returns:
        List of per-OSR cohort dicts matching the janCohort/febCohort structure
    """
    enroll_abbrev = MONTH_ABBREV[enrollment_month]

    # ── Build merchant lookup: branch_id → {name, osr, branch_id} ────────
    merchants_by_osr = defaultdict(list)
    merchant_info = {}  # branch_id -> {name, osr}

    for row in credited_enrollments:
        osr = _get(row, "osr_credit", "Unknown")
        name = _get(row, "merchant_name", "Unknown")
        branch = _get(row, "branch_id", "")

        if not branch or not osr:
            continue

        merchant_info[str(branch)] = {"name": name, "osr": osr}
        merchants_by_osr[osr].append(str(branch))

    # ── Build funding lookup: branch_id → {month_abbrev: dollars} ────────
    merchant_funding = defaultdict(lambda: defaultdict(float))

    for month_key, rows in monthly_activity.items():
        for row in rows:
            branch = str(_get(row, "branch_id", ""))
            if not branch or branch not in merchant_info:
                continue
            funded = _to_float(_get(row, "funded_dollars", 0))
            merchant_funding[branch][month_key] += funded

    # ── Determine which months are relevant (M0, M1, M2) ────────────────
    # M0 = enrollment month, M1 = next month, M2 = month after that
    month_keys = []
    for offset in range(3):  # M0, M1, M2
        m = enrollment_month + offset
        y = enrollment_year
        if m > 12:
            m -= 12
            y += 1
        month_keys.append(MONTH_ABBREV[m])

    # Check which months actually have data
    active_months = [mk for mk in month_keys if mk in monthly_activity]

    # ── Build per-OSR cohort data ────────────────────────────────────────
    cohort = []

    for osr, branch_ids in sorted(merchants_by_osr.items()):
        merchant_count = len(branch_ids)
        producing_count = 0
        osr_monthly_totals = defaultdict(float)
        merchant_list = []

        for branch_id in branch_ids:
            info = merchant_info[branch_id]
            funding = merchant_funding[branch_id]

            # Build per-merchant monthly funding
            merchant_entry = {
                "n": info["name"],
                "b": _try_int(branch_id),
            }

            total_m0_m1 = 0.0
            total_all = 0.0

            for i, mk in enumerate(month_keys):
                amount = round(funding.get(mk, 0.0), 2)
                merchant_entry[mk] = amount
                total_all += amount
                if i < 2:  # M0 + M1
                    total_m0_m1 += amount

            merchant_entry["t"] = round(total_m0_m1, 2)
            merchant_entry["t2"] = round(total_all, 2)

            if total_all > 0:
                producing_count += 1

            # Accumulate OSR monthly totals
            for mk in month_keys:
                osr_monthly_totals[mk] += funding.get(mk, 0.0)

            merchant_list.append(merchant_entry)

        # Sort merchants by total funding descending
        merchant_list.sort(key=lambda x: x["t2"], reverse=True)

        # M0+M1 funded volume
        m0_m1_total = sum(
            osr_monthly_totals[mk] for mk in month_keys[:2]
        )
        # M0+M1+M2 funded volume
        all_total = sum(
            osr_monthly_totals[mk] for mk in month_keys
        )

        osr_entry = {
            "n": osr,
            "m": merchant_count,
            "p": producing_count,
            "f": round(m0_m1_total, 2),
            "f2": round(all_total, 2),
        }

        # Add per-month totals
        for mk in month_keys:
            osr_entry[mk] = round(osr_monthly_totals[mk], 2)

        osr_entry["s"] = merchant_list
        cohort.append(osr_entry)

    # Sort OSRs by M0+M1 funded volume descending
    cohort.sort(key=lambda x: x["f"], reverse=True)

    logger.info(
        "Cohort %s %d: %d OSRs, %d merchants, $%.2f total funded (M0+M1)",
        MONTH_NAMES[enrollment_month], enrollment_year,
        len(cohort),
        sum(e["m"] for e in cohort),
        sum(e["f"] for e in cohort),
    )

    return cohort


def compute_cohort_kpis(cohort: list[dict], enrollment_month: int) -> dict:
    """
    Compute summary KPIs for a cohort.

    Returns:
        Dict with total_funded, total_merchants, producing_merchants,
        at_target_count, total_osrs
    """
    total_funded = sum(e["f"] for e in cohort)
    total_merchants = sum(e["m"] for e in cohort)
    producing_merchants = sum(e["p"] for e in cohort)
    at_target = sum(1 for e in cohort if e["f"] >= COHORT_TARGET_M1)
    total_osrs = len(cohort)

    return {
        "total_funded": round(total_funded, 2),
        "total_funded_display": _format_dollars_short(total_funded),
        "total_merchants": total_merchants,
        "producing_merchants": producing_merchants,
        "at_target_count": at_target,
        "total_osrs": total_osrs,
        "at_target_display": f"{at_target} / {total_osrs}",
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get(row: dict, col_key: str, default: str = "") -> str:
    label = COLUMN_LABELS.get(col_key, col_key)
    return row.get(label, default)


def _to_float(val) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        return 0.0


def _try_int(val):
    """Try to convert to int, return as-is if not possible."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return val


def _format_dollars_short(amount: float) -> str:
    if amount >= 1_000_000:
        return f"${amount/1_000_000:.1f}M"
    elif amount >= 1_000:
        return f"${amount/1_000:.1f}K"
    else:
        return f"${int(amount)}"
