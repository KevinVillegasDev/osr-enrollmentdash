"""
Monthly dashboard data processor.

Transforms Salesforce report data into the JS variable structures
used by monthly dashboard pages (e.g., feb-2026.html).

Inputs: Reports 1-4 (all enrollments, credited enrollments, current month activity, last month activity)
Outputs: Dict of all JS variables + hardcoded KPI values needed by the HTML template.
"""

import logging
from collections import Counter, defaultdict
from datetime import date

from ..config import COLUMN_LABELS, MONTH_NAMES, CHART_PALETTE

logger = logging.getLogger(__name__)


def process(all_enrollments: list[dict], credited_enrollments: list[dict],
            current_month_activity: list[dict], last_month_activity: list[dict],
            month: int, year: int) -> dict:
    """
    Process all 4 reports into the monthly dashboard data structure.

    Args:
        all_enrollments: Rows from Report 1 (New_Enrollments_by_Month)
        credited_enrollments: Rows from Report 2 (Credited_Sales_Team_Enrollments)
        current_month_activity: Rows from Report 3 (Current_Month_Enrollment_Activity_Report)
        last_month_activity: Rows from Report 4 (Last_Month_Enrollment_Activity_Report)
        month: Dashboard month (1-12)
        year: Dashboard year

    Returns:
        Dict with all data needed to render the monthly dashboard
    """
    month_name = MONTH_NAMES[month]
    month_abbrev = month_name[:3]

    # ── repCredits: OSR enrollment counts ────────────────────────────────
    osr_counts = Counter()
    for row in credited_enrollments:
        osr = _get(row, "osr_credit", "Unknown")
        if osr:
            osr_counts[osr] += 1

    rep_credits = sorted(
        [{"n": name, "v": count} for name, count in osr_counts.items()],
        key=lambda x: x["v"], reverse=True
    )

    # ── marketData / marketDataFull: State counts ────────────────────────
    osr_states = Counter()
    for row in credited_enrollments:
        state = _get(row, "billing_state", "Unknown")
        if state:
            osr_states[state] += 1

    all_states = Counter()
    for row in all_enrollments:
        state = _get(row, "billing_state", "Unknown")
        if state:
            all_states[state] += 1

    market_data = _counter_to_sorted_list(osr_states)
    market_data_full = _counter_to_sorted_list(all_states)

    # ── industryData / industryDataFull ──────────────────────────────────
    osr_industries = Counter()
    for row in credited_enrollments:
        industry = _get(row, "industry", "Other")
        osr_industries[industry or "Other"] += 1

    all_industries = Counter()
    for row in all_enrollments:
        industry = _get(row, "industry", "Other")
        all_industries[industry or "Other"] += 1

    industry_data = _counter_to_sorted_list(osr_industries)
    industry_data_full = _counter_to_sorted_list(all_industries)

    # ── isrData: ISR assignment distribution ─────────────────────────────
    isr_counts = Counter()
    for row in credited_enrollments:
        isr = _get(row, "isr_assignment")
        if isr:
            isr_counts[isr] += 1

    isr_data = _counter_to_sorted_list(isr_counts)

    # ── dailyTrend: Enrollments per day ──────────────────────────────────
    daily_counts = Counter()
    for row in credited_enrollments:
        enroll_date = _get(row, "enrollment_date", "")
        if enroll_date:
            try:
                dt = _parse_date(enroll_date)
                label = f"{month_abbrev} {dt.day}"
                daily_counts[dt] = daily_counts.get(dt, 0) + 1
            except (ValueError, TypeError):
                pass

    daily_trend = []
    for dt in sorted(daily_counts.keys()):
        label = f"{month_abbrev} {dt.day}"
        daily_trend.append({"d": label, "v": daily_counts[dt]})

    # ── Build merchant activity lookup (from Reports 3 + 4) ─────────────
    # Key by branch ID → {funded_dollars, funded_apps, total_apps}
    merchant_activity = defaultdict(lambda: {"funded": 0.0, "funded_apps": 0, "total_apps": 0})

    for row in current_month_activity + last_month_activity:
        branch = _get(row, "branch_id", "")
        if not branch:
            continue
        funded = _to_float(_get(row, "funded_dollars", 0))
        funded_apps = _to_int(_get(row, "funded_apps", 0))
        total_apps = _to_int(_get(row, "total_apps", 0))
        merchant_activity[branch]["funded"] += funded
        merchant_activity[branch]["funded_apps"] += funded_apps
        merchant_activity[branch]["total_apps"] += total_apps

    # ── repMerchants: Per-OSR merchant detail with funding ───────────────
    rep_merchants = defaultdict(list)
    all_merchant_rows = []

    for row in credited_enrollments:
        osr = _get(row, "osr_credit", "Unknown")
        name = _get(row, "merchant_name", "Unknown")
        city = _get(row, "billing_city", "")
        state = _get(row, "billing_state", "")
        branch = _get(row, "branch_id", "")

        location = f"{city}, {state}" if city and state else (city or state or "")

        activity = merchant_activity.get(branch, {"funded": 0, "funded_apps": 0, "total_apps": 0})

        merchant = {
            "n": name,
            "l": location,
            "f": round(activity["funded"], 2),
            "fa": activity["funded_apps"],
            "ta": activity["total_apps"],
        }

        rep_merchants[osr].append(merchant)
        all_merchant_rows.append({**merchant, "osr": osr, "branch": branch})

    # Sort each rep's merchants by funded volume descending
    for osr in rep_merchants:
        rep_merchants[osr].sort(key=lambda x: x["f"], reverse=True)

    # ── topProducers: Top 15 merchants by funded volume ──────────────────
    # Build from all enrollments (not just credited) with activity data
    all_merchants_with_funding = []
    for row in all_enrollments:
        name = _get(row, "merchant_name", "Unknown")
        branch = _get(row, "branch_id", "")
        osr = _get(row, "osr_credit", "")

        activity = merchant_activity.get(branch, {"funded": 0, "funded_apps": 0, "total_apps": 0})
        funded = activity["funded"]
        funded_apps = activity["funded_apps"]
        total_apps = activity["total_apps"]

        if funded > 0 or total_apps > 0:
            rate = round((funded_apps / total_apps * 100), 1) if total_apps > 0 else 0.0
            all_merchants_with_funding.append({
                "n": name,
                "f": round(funded, 2),
                "fa": funded_apps,
                "ta": total_apps,
                "r": f"{rate}%",
                "o": osr or "",
            })

    all_merchants_with_funding.sort(key=lambda x: x["f"], reverse=True)
    top_producers = all_merchants_with_funding[:15]

    # ── KPI calculations ─────────────────────────────────────────────────
    kpi_total_enrollments = len(all_enrollments)
    kpi_osr_credited = len(credited_enrollments)
    kpi_credit_pct = round(kpi_osr_credited / kpi_total_enrollments * 100, 1) if kpi_total_enrollments > 0 else 0
    kpi_other = kpi_total_enrollments - kpi_osr_credited
    kpi_other_pct = round(100 - kpi_credit_pct, 1)

    total_funded = sum(m["funded"] for m in merchant_activity.values())
    total_funded_apps = sum(m["funded_apps"] for m in merchant_activity.values())
    total_apps = sum(m["total_apps"] for m in merchant_activity.values())
    kpi_conversion = round(total_funded_apps / total_apps * 100, 1) if total_apps > 0 else 0
    kpi_avg_ticket = round(total_funded / total_funded_apps) if total_funded_apps > 0 else 0

    active_merchants = sum(1 for m in merchant_activity.values() if m["total_apps"] > 0)
    producing_merchants = sum(1 for m in merchant_activity.values() if m["funded"] > 0)

    # ── Product mix (LTO vs RC) ──────────────────────────────────────────
    osr_lto, osr_rc = 0, 0
    for row in credited_enrollments:
        product = _get(row, "product_type", "")
        if product and "lease" in product.lower():
            osr_lto += 1
        else:
            osr_rc += 1

    all_lto, all_rc = 0, 0
    for row in all_enrollments:
        product = _get(row, "product_type", "")
        if product and "lease" in product.lower():
            all_lto += 1
        else:
            all_rc += 1

    osr_lto_pct = round(osr_lto / (osr_lto + osr_rc) * 100, 1) if (osr_lto + osr_rc) > 0 else 0
    osr_rc_pct = round(100 - osr_lto_pct, 1)
    all_lto_pct = round(all_lto / (all_lto + all_rc) * 100, 1) if (all_lto + all_rc) > 0 else 0
    all_rc_pct = round(100 - all_lto_pct, 1)

    # ── Funnel values ────────────────────────────────────────────────────
    funnel = [
        {"l": "Active Merchants", "v": active_merchants, "w": 100, "c": "#3B82F6"},
        {"l": "Total Applications", "v": total_apps, "w": 85, "c": "#8B5CF6"},
        {"l": "Funded Applications", "v": total_funded_apps,
         "w": max(10, round(total_funded_apps / max(total_apps, 1) * 100)), "c": "#10B981"},
        {"l": "Producing Merchants", "v": producing_merchants,
         "w": max(10, round(producing_merchants / max(active_merchants, 1) * 100)), "c": "#F59E0B"},
    ]

    # ── Auto-generate observations ───────────────────────────────────────
    observations = _generate_observations(top_producers, total_funded, all_merchant_rows)

    # ── Daily pace callout ───────────────────────────────────────────────
    peak_day = max(daily_trend, key=lambda x: x["v"]) if daily_trend else {"d": "N/A", "v": 0}
    avg_daily = round(kpi_osr_credited / max(len(daily_trend), 1), 1)

    # ── Format funded volume for display ─────────────────────────────────
    kpi_funded_display = _format_dollars(total_funded)
    kpi_funded_short = _format_dollars_short(total_funded)

    return {
        # JS data variables
        "repCredits": rep_credits,
        "marketData": market_data,
        "marketDataFull": market_data_full,
        "industryData": industry_data,
        "industryDataFull": industry_data_full,
        "isrData": isr_data,
        "dailyTrend": daily_trend,
        "topProducers": top_producers,
        "repMerchants": dict(rep_merchants),
        "PC": CHART_PALETTE,
        "marketsScope": "osr",
        # Funnel & observations
        "fi": funnel,
        "obs": observations,
        # Product mix
        "osr_product_mix": [osr_lto, osr_rc],
        "all_product_mix": [all_lto, all_rc],
        "osr_lto_pct": osr_lto_pct,
        "osr_rc_pct": osr_rc_pct,
        "all_lto_pct": all_lto_pct,
        "all_rc_pct": all_rc_pct,
        # KPIs
        "kpi_total": kpi_total_enrollments,
        "kpi_osr": kpi_osr_credited,
        "kpi_credit_pct": kpi_credit_pct,
        "kpi_other": kpi_other,
        "kpi_other_pct": kpi_other_pct,
        "kpi_funded_display": kpi_funded_display,
        "kpi_funded_short": kpi_funded_short,
        "kpi_funded_apps": total_funded_apps,
        "kpi_total_apps": total_apps,
        "kpi_conversion": kpi_conversion,
        "kpi_avg_ticket": f"${kpi_avg_ticket:,}",
        "kpi_active_merchants": active_merchants,
        "kpi_producing_merchants": producing_merchants,
        # Daily pace
        "peak_day": peak_day["d"],
        "peak_day_count": peak_day["v"],
        "avg_daily": avg_daily,
        # Metadata
        "month": month,
        "year": year,
        "month_name": month_name,
        "month_abbrev": month_abbrev,
        "last_updated": date.today().strftime("%b %-d, %Y"),
    }


# ── Helper functions ─────────────────────────────────────────────────────────

def _get(row: dict, col_key: str, default: str = "") -> str:
    """Get a value from a row dict using the column label mapping."""
    label = COLUMN_LABELS.get(col_key, col_key)
    return row.get(label, default)


def _to_float(val) -> float:
    """Safely convert a value to float."""
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        return 0.0


def _to_int(val) -> int:
    """Safely convert a value to int."""
    if isinstance(val, int):
        return val
    try:
        return int(float(str(val).replace(",", "")))
    except (ValueError, TypeError):
        return 0


def _parse_date(val) -> date:
    """Parse a date value from Salesforce (ISO format or various formats)."""
    if isinstance(val, date):
        return val
    s = str(val).strip()
    # Try ISO format first
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ", "%m/%d/%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {val}")


def _counter_to_sorted_list(counter: Counter) -> list[dict]:
    """Convert a Counter to a sorted list of {n, v} dicts."""
    return sorted(
        [{"n": name, "v": count} for name, count in counter.items()],
        key=lambda x: x["v"], reverse=True
    )


def _format_dollars(amount: float) -> str:
    """Format dollar amount for KPI display: $166,552"""
    return f"${int(round(amount)):,}"


def _format_dollars_short(amount: float) -> str:
    """Format dollar amount as short display: $167K"""
    if amount >= 1_000_000:
        return f"${amount/1_000_000:.1f}M"
    elif amount >= 1_000:
        return f"${amount/1_000:.0f}K"
    else:
        return f"${int(amount)}"


def _generate_observations(top_producers: list, total_funded: float,
                           all_merchants: list) -> list[dict]:
    """Auto-generate key observations from production data."""
    obs = []

    if top_producers:
        # Top merchant
        top = top_producers[0]
        pct_of_total = round(top["f"] / total_funded * 100, 1) if total_funded > 0 else 0
        obs.append({
            "i": "\U0001f3c6",  # trophy
            "t": f"{top['n']} leads all merchants at ${top['f']:,.0f} funded "
                 f"({pct_of_total}% of total volume)"
        })

        # Top 5 concentration
        if len(top_producers) >= 5:
            top5_total = sum(p["f"] for p in top_producers[:5])
            top5_pct = round(top5_total / total_funded * 100, 1) if total_funded > 0 else 0
            obs.append({
                "i": "\u26a1",  # lightning
                "t": f"Top 5 merchants account for ${top5_total:,.0f} ({top5_pct}%) of all funded volume"
            })

        # Highest conversion rate among top producers
        best_conv = max(
            (p for p in top_producers if p["ta"] >= 3),
            key=lambda p: float(p["r"].rstrip("%")),
            default=None
        )
        if best_conv:
            obs.append({
                "i": "\U0001f3af",  # target
                "t": f"{best_conv['n']} has the highest conversion rate among top producers at "
                     f"{best_conv['r']} ({best_conv['fa']}/{best_conv['ta']} apps funded)"
            })

        # Non-auto vertical check
        non_auto_keywords = ["pet", "puppy", "puppies", "phone", "air"]
        non_auto_total = sum(
            m["f"] for m in all_merchants
            if any(kw in m["n"].lower() for kw in non_auto_keywords) and m["f"] > 0
        )
        if non_auto_total > 0 and total_funded > 0:
            non_auto_pct = round(non_auto_total / total_funded * 100, 1)
            obs.append({
                "i": "\U0001f4c8",  # chart
                "t": f"Non-auto verticals driving ${non_auto_total:,.0f} -- "
                     f"{non_auto_pct}% of total production"
            })

    return obs if obs else [{"i": "\U0001f4ca", "t": "Production data will populate as merchants begin funding."}]
