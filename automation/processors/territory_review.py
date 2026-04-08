"""
Territory review processor.

Produces a per-territory cohort review matching the structure of the
quarterly territory deck.  Takes data from multiple pipeline sources
(cohort tracking, field activity, ISR notes, enrollment data, Genesys)
and returns a single dict keyed by section.

Sections: summary, cohort_scorecard, activity_vs_output, isr_conditioning,
producer_patterns, gaps, pipeline.
"""

import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from ..config import (
    COLUMN_LABELS,
    MONTH_ABBREV,
    MONTH_NAMES,
    OSR_ROSTER,
    ISR_ROSTER,
    ISR_TERRITORY_MAP,
    TERRITORY_MAP,
    COHORT_TARGET_M1,
    COHORT_TARGET_M2,
)

logger = logging.getLogger(__name__)

# Reverse lookup: abbreviation -> month number
_ABBREV_TO_NUM = {v: k for k, v in MONTH_ABBREV.items()}


# ═══════════════════════════════════════════════════════════════════════════
#  Main entry point
# ═══════════════════════════════════════════════════════════════════════════

def process(territory_code: str,
            osr_name: str,
            quarter_months: list[int],
            year: int,
            cohorts: dict,
            field_activity: dict,
            isr_notes: list[dict],
            enrollment_data: dict,
            genesys_data: list) -> dict:
    """
    Build a full territory review for one OSR across a quarter.

    Args:
        territory_code: e.g. "LTO-7"
        osr_name: e.g. "Stephanie Whitlock"
        quarter_months: e.g. [1, 2, 3] for Q1
        year: e.g. 2026
        cohorts: Maps var name -> cohort array from cohort_tracking.process_cohort()
                 e.g. {"janCohort": [...], "febCohort": [...], "marCohort": [...]}
        field_activity: Output from field_activity.process() (repActivity, repStops)
        isr_notes: Raw ISR Notes report rows (all territories)
        enrollment_data: Maps month_abbrev -> list of credited enrollment rows
        genesys_data: Genesys talk time data (all ISRs)

    Returns:
        Dict with keys: summary, cohort_scorecard, activity_vs_output,
        isr_conditioning, producer_patterns, gaps, pipeline
    """
    logger.info("Processing territory review for %s (%s)", territory_code, osr_name)

    # ── Gather the OSR's BIDs across all months ──────────────────────────
    all_bids = _get_territory_bids(enrollment_data, osr_name)
    bid_set = set(all_bids.keys())

    # ── Map each BID to its enrollment month and merchant name ───────────
    bid_enrollment_date = {}   # bid -> date
    bid_merchant_name = {}     # bid -> str
    bid_cohort_month = {}      # bid -> month_abbrev

    for month_abbrev, rows in enrollment_data.items():
        for row in rows:
            osr = _resolve_osr(row)
            if osr != osr_name:
                continue
            bid = _extract_bid(row)
            if not bid:
                continue
            name = row.get(COLUMN_LABELS.get("merchant_name", "Account Name"), "")
            # Try label version for SUMMARY format
            label_name = row.get(f"_label_{COLUMN_LABELS.get('merchant_name', 'Account Name')}", "")
            if label_name and label_name != "-":
                name = label_name
            bid_merchant_name[bid] = name or f"BID {bid}"
            bid_cohort_month[bid] = month_abbrev
            enroll_date = _parse_enrollment_date(row)
            if enroll_date:
                bid_enrollment_date[bid] = enroll_date

    # ── Filter ISR notes to this territory's BIDs ────────────────────────
    territory_notes = _filter_isr_notes(isr_notes, bid_set)

    # ── Extract per-OSR cohort data across months ────────────────────────
    osr_cohorts = _extract_osr_cohorts(cohorts, osr_name, quarter_months)

    # ── Compute ISR touch data ───────────────────────────────────────────
    isr_touch_data = _compute_isr_touches(territory_notes, bid_set)
    total_isr_touches = sum(isr_touch_data.values())

    # ── Derive primary ISR (static map first, note frequency as override) ─
    primary_isr = ISR_TERRITORY_MAP.get(territory_code, "")
    isr_from_notes = _derive_primary_isr(territory_notes)
    if isr_from_notes:
        primary_isr = isr_from_notes

    # ── Field activity for this rep ──────────────────────────────────────
    tsr_checkins = _get_rep_checkins(field_activity, osr_name)

    # ── Days to first touch per BID ──────────────────────────────────────
    days_to_first_touch = _compute_days_to_first_touch(
        territory_notes, bid_enrollment_date
    )

    # ── OB sequence detection per BID ────────────────────────────────────
    ob_sequences = {}
    for bid in bid_set:
        ob_sequences[bid] = _detect_ob_sequence(territory_notes, bid)

    # ── Funding data from cohort structures ──────────────────────────────
    bid_funding = _extract_bid_funding(osr_cohorts)

    # ── Build each section ───────────────────────────────────────────────
    summary = _build_summary(
        osr_name, primary_isr, osr_cohorts, quarter_months, year,
        total_isr_touches, tsr_checkins, bid_set, isr_touch_data
    )

    cohort_scorecard = _build_cohort_scorecard(
        osr_cohorts, quarter_months, year
    )

    activity_vs_output = _build_activity_vs_output(
        osr_cohorts, quarter_months, tsr_checkins, total_isr_touches,
        territory_notes, bid_set, bid_funding, isr_touch_data,
        days_to_first_touch
    )

    isr_conditioning = _build_isr_conditioning(
        osr_cohorts, quarter_months, year, territory_notes,
        days_to_first_touch, bid_cohort_month
    )

    producer_patterns = _build_producer_patterns(
        osr_cohorts, bid_funding, ob_sequences, bid_merchant_name,
        bid_cohort_month, quarter_months
    )

    gaps = _build_gaps(
        bid_set, bid_enrollment_date, bid_merchant_name, bid_funding,
        territory_notes, ob_sequences, days_to_first_touch
    )

    pipeline = _build_pipeline(
        bid_set, bid_merchant_name, bid_funding, ob_sequences,
        bid_enrollment_date, bid_cohort_month, territory_notes
    )

    logger.info(
        "Territory review for %s: %d BIDs, %d ISR touches, %d field stops, "
        "$%.2f total funding",
        territory_code, len(bid_set), total_isr_touches, tsr_checkins,
        summary["total_funding"],
    )

    return {
        "summary": summary,
        "cohort_scorecard": cohort_scorecard,
        "activity_vs_output": activity_vs_output,
        "isr_conditioning": isr_conditioning,
        "producer_patterns": producer_patterns,
        "gaps": gaps,
        "pipeline": pipeline,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Section builders
# ═══════════════════════════════════════════════════════════════════════════

def _build_summary(osr_name, primary_isr, osr_cohorts, quarter_months, year,
                   total_isr_touches, tsr_checkins, bid_set, isr_touch_data):
    """Build the top-level summary banner."""
    total_enrolled = 0
    total_producing = 0
    total_funding = 0.0

    for entry in osr_cohorts.values():
        if entry:
            total_enrolled += entry.get("m", 0)
            total_producing += entry.get("p", 0)
            total_funding += entry.get("f2", 0.0)

    num_cohort_months = len(quarter_months)
    funding_standard = COHORT_TARGET_M1 * num_cohort_months
    funding_pct = round(total_funding / funding_standard * 100, 1) if funding_standard else 0.0

    # Zero-touch BIDs: enrolled but never contacted by ISR
    touched_bids = {bid for bid, count in isr_touch_data.items() if count > 0}
    zero_touch_bids = len(bid_set - touched_bids)

    return {
        "total_enrolled": total_enrolled,
        "total_producing": total_producing,
        "total_funding": round(total_funding, 2),
        "funding_standard": funding_standard,
        "funding_pct": funding_pct,
        "isr_touches": total_isr_touches,
        "tsr_checkins": tsr_checkins,
        "zero_touch_bids": zero_touch_bids,
        "osr_name": osr_name,
        "isr_name": primary_isr or "N/A",
    }


def _build_cohort_scorecard(osr_cohorts, quarter_months, year):
    """Build per-month cohort cards with maturity and pass/fail status."""
    today = date.today()
    scorecard = []

    for month_num in quarter_months:
        abbrev = MONTH_ABBREV[month_num]
        entry = osr_cohorts.get(abbrev)

        enrolled = entry.get("m", 0) if entry else 0
        producing = entry.get("p", 0) if entry else 0
        m1_funding = entry.get("f", 0.0) if entry else 0.0

        pass_15k = m1_funding >= COHORT_TARGET_M1
        pass_30k = (entry.get("f2", 0.0) if entry else 0.0) >= COHORT_TARGET_M2

        maturity = _compute_maturity(month_num, year, today)

        scorecard.append({
            "month": MONTH_NAMES[month_num],
            "month_abbrev": abbrev,
            "enrolled": enrolled,
            "producing": producing,
            "producing_ratio": f"{producing} of {enrolled}",
            "m1_funding": round(m1_funding, 2),
            "pass_15k": pass_15k,
            "pass_30k": pass_30k,
            "maturity": maturity,
        })

    return scorecard


def _build_activity_vs_output(osr_cohorts, quarter_months, tsr_checkins,
                              total_isr_touches, territory_notes, bid_set,
                              bid_funding, isr_touch_data, days_to_first_touch):
    """Build activity-vs-output side-by-side metrics."""
    total_enrolled = 0
    total_producing = 0
    total_funding = 0.0

    for entry in osr_cohorts.values():
        if entry:
            total_enrolled += entry.get("m", 0)
            total_producing += entry.get("p", 0)
            total_funding += entry.get("f2", 0.0)

    num_cohort_months = len(quarter_months)
    funding_standard = COHORT_TARGET_M1 * num_cohort_months
    funding_pct = round(total_funding / funding_standard * 100, 1) if funding_standard else 0.0

    # Call entries from ISR notes
    call_entries = sum(
        1 for note in territory_notes
        if _get_note_field(note, "isr_note_subject") in
        ("Call", "OB1 Welcome", "OB2 Demo", "OB3 Follow Up", "OB Final")
    )

    # Zero-touch BIDs
    touched_bids = {bid for bid, count in isr_touch_data.items() if count > 0}
    zero_touch_bids = len(bid_set - touched_bids)

    # Average days to first touch for the most recent cohort month
    recent_month = MONTH_ABBREV[quarter_months[-1]]
    recent_bids = [
        bid for bid in bid_set
        if bid in days_to_first_touch
    ]
    # Filter to most recent month's BIDs
    recent_month_bids = []
    for entry in osr_cohorts.get(recent_month, {}).get("s", []) if osr_cohorts.get(recent_month) else []:
        bid_val = entry.get("b")
        if bid_val is not None:
            recent_month_bids.append(str(bid_val))

    recent_ftd = [
        days_to_first_touch[bid]
        for bid in recent_month_bids
        if bid in days_to_first_touch
    ]
    avg_days_first_touch = round(sum(recent_ftd) / len(recent_ftd), 1) if recent_ftd else 0.0

    # Concentration: top producer
    concentration_bid = ""
    concentration_pct = 0.0
    if bid_funding and total_funding > 0:
        top_bid = max(bid_funding, key=bid_funding.get)
        concentration_bid_name = ""
        # Look up name from cohort merchant lists
        for entry in osr_cohorts.values():
            if not entry:
                continue
            for merch in entry.get("s", []):
                if str(merch.get("b")) == str(top_bid):
                    concentration_bid_name = merch.get("n", f"BID {top_bid}")
                    break
            if concentration_bid_name:
                break
        concentration_bid = concentration_bid_name or f"BID {top_bid}"
        concentration_pct = round(bid_funding[top_bid] / total_funding * 100, 1)

    return {
        "tsr_checkins": tsr_checkins,
        "producing_ratio": f"{total_producing} / {total_enrolled}",
        "isr_touches": total_isr_touches,
        "total_funding": round(total_funding, 2),
        "call_entries": call_entries,
        "funding_standard": funding_standard,
        "zero_touch_bids": zero_touch_bids,
        "funding_pct": funding_pct,
        "avg_days_first_touch": avg_days_first_touch,
        "concentration_bid": concentration_bid,
        "concentration_pct": concentration_pct,
    }


def _build_isr_conditioning(osr_cohorts, quarter_months, year,
                            territory_notes, days_to_first_touch,
                            bid_cohort_month):
    """Build per-cohort ISR conditioning table."""
    conditioning = []
    prev_producing = None

    for month_num in quarter_months:
        abbrev = MONTH_ABBREV[month_num]
        entry = osr_cohorts.get(abbrev)

        bid_count = entry.get("m", 0) if entry else 0
        producing = entry.get("p", 0) if entry else 0
        m1_funding = entry.get("f", 0.0) if entry else 0.0

        # Average days to first touch for this cohort's BIDs
        cohort_bids = []
        if entry:
            for merch in entry.get("s", []):
                bid_val = merch.get("b")
                if bid_val is not None:
                    cohort_bids.append(str(bid_val))

        ftd_values = [
            days_to_first_touch[bid]
            for bid in cohort_bids
            if bid in days_to_first_touch
        ]
        avg_ftd = round(sum(ftd_values) / len(ftd_values), 1) if ftd_values else 0.0

        # OB2 completion count: how many BIDs have OB2 Demo logged
        ob2_completed = 0
        for bid in cohort_bids:
            ob = _detect_ob_sequence(territory_notes, bid)
            if ob.get("ob2"):
                ob2_completed += 1

        # Trend detection
        if prev_producing is None:
            trend = "baseline"
        elif producing > prev_producing:
            trend = "improving"
        elif producing < prev_producing:
            trend = "declining"
        else:
            trend = "baseline"

        prev_producing = producing

        conditioning.append({
            "month": MONTH_NAMES[month_num],
            "bid_count": bid_count,
            "avg_days_first_touch": avg_ftd,
            "ob2_completed": ob2_completed,
            "ob2_total": bid_count,
            "producing": producing,
            "m1_funding": round(m1_funding, 2),
            "trend": trend,
        })

    return conditioning


def _build_producer_patterns(osr_cohorts, bid_funding, ob_sequences,
                             bid_merchant_name, bid_cohort_month,
                             quarter_months):
    """Build producing BIDs table with pattern analysis."""
    producers = []

    for abbrev, entry in osr_cohorts.items():
        if not entry:
            continue
        month_num = _ABBREV_TO_NUM.get(abbrev)
        if month_num not in quarter_months:
            continue

        for merch in entry.get("s", []):
            total_funded = merch.get("t2", 0.0)
            if total_funded <= 0:
                continue

            bid = str(merch.get("b", ""))
            ob = ob_sequences.get(bid, {})
            pattern = _classify_producer_pattern(ob)

            producers.append({
                "merchant": merch.get("n", f"BID {bid}"),
                "bid": merch.get("b"),
                "cohort_month": MONTH_NAMES.get(month_num, abbrev),
                "q_funding": round(total_funded, 2),
                "ob2_done": ob.get("ob2", False),
                "spiff_active": False,  # Cannot determine from current data
                "pattern": pattern,
            })

    # Sort by funding descending
    producers.sort(key=lambda x: x["q_funding"], reverse=True)
    return producers


def _build_gaps(bid_set, bid_enrollment_date, bid_merchant_name,
                bid_funding, territory_notes, ob_sequences,
                days_to_first_touch):
    """Auto-detect issues: 72-hour violations, missing OB steps, etc."""
    gaps = []

    # ── 72-hour contact violations ───────────────────────────────────────
    violations_72h = []
    for bid in bid_set:
        ftd = days_to_first_touch.get(bid)
        enroll_date = bid_enrollment_date.get(bid)
        if ftd is not None and ftd > 3:
            first_touch_date = _find_first_touch_date(territory_notes, bid)
            violations_72h.append({
                "bid": _try_int(bid),
                "merchant": bid_merchant_name.get(bid, f"BID {bid}"),
                "enrolled": _format_short_date(enroll_date),
                "first_touch": _format_short_date(first_touch_date),
                "days_late": int(ftd) - 3,
                "funding": round(bid_funding.get(bid, 0.0), 2),
            })

    if violations_72h:
        violations_72h.sort(key=lambda x: x["days_late"], reverse=True)
        gaps.append({
            "type": "72_hour_violation",
            "title": "72-Hour Contact Violation",
            "count": len(violations_72h),
            "total": len(bid_set),
            "details": violations_72h,
        })

    # ── Missing OB1 Welcome ──────────────────────────────────────────────
    missing_ob1 = []
    for bid in bid_set:
        ob = ob_sequences.get(bid, {})
        if not ob.get("ob1"):
            missing_ob1.append({
                "bid": _try_int(bid),
                "merchant": bid_merchant_name.get(bid, f"BID {bid}"),
                "funding": round(bid_funding.get(bid, 0.0), 2),
            })

    if missing_ob1:
        missing_ob1.sort(key=lambda x: x["bid"] if isinstance(x["bid"], int) else 0)
        gaps.append({
            "type": "missing_ob1",
            "title": "OB1 Welcome Missing",
            "count": len(missing_ob1),
            "total": len(bid_set),
            "details": missing_ob1,
        })

    # ── Missing OB2 Demo ─────────────────────────────────────────────────
    missing_ob2 = []
    for bid in bid_set:
        ob = ob_sequences.get(bid, {})
        if ob.get("ob1") and not ob.get("ob2"):
            missing_ob2.append({
                "bid": _try_int(bid),
                "merchant": bid_merchant_name.get(bid, f"BID {bid}"),
                "funding": round(bid_funding.get(bid, 0.0), 2),
            })

    if missing_ob2:
        missing_ob2.sort(key=lambda x: x["bid"] if isinstance(x["bid"], int) else 0)
        gaps.append({
            "type": "missing_ob2",
            "title": "OB2 Demo Not Completed (OB1 done)",
            "count": len(missing_ob2),
            "total": len(bid_set),
            "details": missing_ob2,
        })

    # ── Zero-funded enrolled > 30 days ───────────────────────────────────
    today = date.today()
    stale_zero = []
    for bid in bid_set:
        enroll_date = bid_enrollment_date.get(bid)
        funded = bid_funding.get(bid, 0.0)
        if enroll_date and funded <= 0:
            days_since = (today - enroll_date).days
            if days_since > 30:
                stale_zero.append({
                    "bid": _try_int(bid),
                    "merchant": bid_merchant_name.get(bid, f"BID {bid}"),
                    "days_since_enrollment": days_since,
                    "ob_progress": _ob_summary_str(ob_sequences.get(bid, {})),
                })

    if stale_zero:
        stale_zero.sort(key=lambda x: x["days_since_enrollment"], reverse=True)
        gaps.append({
            "type": "stale_zero_funded",
            "title": "Enrolled > 30 Days, Zero Funding",
            "count": len(stale_zero),
            "total": len(bid_set),
            "details": stale_zero,
        })

    return gaps


def _build_pipeline(bid_set, bid_merchant_name, bid_funding, ob_sequences,
                    bid_enrollment_date, bid_cohort_month, territory_notes):
    """Categorize BIDs into action pipeline: HIGH, RETAIN, GROW, ACT_NOW."""
    today = date.today()
    pipeline = []

    for bid in bid_set:
        funded = bid_funding.get(bid, 0.0)
        ob = ob_sequences.get(bid, {})
        enroll_date = bid_enrollment_date.get(bid)
        days_since = (today - enroll_date).days if enroll_date else 0
        merchant = bid_merchant_name.get(bid, f"BID {bid}")

        category, reason, next_step = _categorize_bid(
            funded, ob, days_since, enroll_date, merchant, territory_notes, bid
        )

        if category:
            pipeline.append({
                "category": category,
                "merchant": merchant,
                "bid": _try_int(bid),
                "funding": round(funded, 2),
                "reason": reason,
                "next_step": next_step,
            })

    # Sort: HIGH first, then ACT_NOW, GROW, RETAIN
    category_order = {"HIGH": 0, "ACT_NOW": 1, "GROW": 2, "RETAIN": 3}
    pipeline.sort(key=lambda x: (category_order.get(x["category"], 9), -x["funding"]))

    return pipeline


# ═══════════════════════════════════════════════════════════════════════════
#  Helper functions
# ═══════════════════════════════════════════════════════════════════════════

def _parse_date(val) -> date | None:
    """Parse a date string to datetime.date.  Handles multiple formats."""
    if not val:
        return None
    if isinstance(val, date):
        return val
    s = str(val).strip()

    # "M/D/YYYY" or "M/D/YYYY, H:MM AM/PM"
    if "/" in s:
        date_part = s.split(",")[0].strip()
        try:
            parts = date_part.split("/")
            if len(parts) == 3:
                return date(int(parts[2]), int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            pass

    # "YYYY-MM-DD" or "YYYY-MM-DDT..."
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        pass

    return None


def _business_days_between(start: date, end: date) -> int:
    """Count weekday days between start and end (inclusive of both)."""
    if start > end:
        return 0
    count = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def _get_territory_bids(enrollment_data: dict, osr_name: str) -> dict:
    """
    Get all BIDs credited to this OSR across all months.

    Returns:
        Dict mapping bid (str) -> month_abbrev of enrollment
    """
    bids = {}
    for month_abbrev, rows in enrollment_data.items():
        for row in rows:
            osr = _resolve_osr(row)
            if osr != osr_name:
                continue
            bid = _extract_bid(row)
            if bid:
                bids[bid] = month_abbrev
    return bids


def _resolve_osr(row: dict) -> str:
    """Resolve the OSR name from a row, matching normalization logic."""
    label = COLUMN_LABELS.get("osr_credit", "OSR Enrollment Credit")
    val = row.get(label, "")
    if val and val != "-":
        return val
    for alt_key in ("_label_OSR", "_label_OSR Enrollment Credit",
                    "Referral/Promo Code"):
        alt_val = row.get(alt_key)
        if alt_val and alt_val != "-":
            return alt_val
    return ""


def _extract_bid(row: dict) -> str:
    """Extract branch ID as string from a row."""
    bid = row.get(COLUMN_LABELS.get("branch_id", "Branch ID"), "")
    if not bid or bid == "-":
        return ""
    try:
        return str(int(float(str(bid))))
    except (ValueError, TypeError):
        return str(bid)


def _parse_enrollment_date(row: dict) -> date | None:
    """Extract and parse the enrollment date from a row."""
    label = COLUMN_LABELS.get("enrollment_date", "Enrollment Date")
    val = row.get(label) or row.get(f"_label_{label}", "")
    return _parse_date(val)


def _filter_isr_notes(isr_notes: list[dict], bid_set: set) -> list[dict]:
    """Filter ISR notes to only those matching BIDs in the territory."""
    filtered = []
    bid_label = COLUMN_LABELS.get("isr_note_branch_id", "Branch ID")

    for note in isr_notes:
        bid_raw = note.get(bid_label, "")
        try:
            bid = str(int(float(str(bid_raw))))
        except (ValueError, TypeError):
            continue
        if bid in bid_set:
            filtered.append(note)
    return filtered


def _extract_osr_cohorts(cohorts: dict, osr_name: str,
                         quarter_months: list[int]) -> dict:
    """
    Extract the OSR's cohort entry for each month in the quarter.

    Returns:
        Dict mapping month_abbrev -> osr cohort entry (or None)
    """
    result = {}

    for month_num in quarter_months:
        abbrev = MONTH_ABBREV[month_num]
        # Try common cohort key patterns
        cohort_key = f"{abbrev}Cohort"
        cohort_list = cohorts.get(cohort_key, [])

        osr_entry = None
        for entry in cohort_list:
            if entry.get("n") == osr_name:
                osr_entry = entry
                break

        result[abbrev] = osr_entry

    return result


def _compute_isr_touches(territory_notes: list[dict],
                         bid_set: set) -> dict:
    """
    Count ISR touches per BID.

    Returns:
        Dict mapping bid (str) -> touch count
    """
    touch_counts = defaultdict(int)
    bid_label = COLUMN_LABELS.get("isr_note_branch_id", "Branch ID")

    # Initialize all BIDs with 0
    for bid in bid_set:
        touch_counts[bid] = 0

    for note in territory_notes:
        bid_raw = note.get(bid_label, "")
        try:
            bid = str(int(float(str(bid_raw))))
        except (ValueError, TypeError):
            continue
        if bid in bid_set:
            touch_counts[bid] += 1

    return dict(touch_counts)


def _compute_days_to_first_touch(territory_notes: list[dict],
                                 bid_enrollment_date: dict) -> dict:
    """
    Compute days between enrollment and first ISR touch per BID.

    Returns:
        Dict mapping bid (str) -> days (float)
    """
    # Find earliest ISR note date per BID
    bid_first_touch = {}
    bid_label = COLUMN_LABELS.get("isr_note_branch_id", "Branch ID")
    date_label = COLUMN_LABELS.get("isr_note_date", "_label_Created Date")

    for note in territory_notes:
        bid_raw = note.get(bid_label, "")
        try:
            bid = str(int(float(str(bid_raw))))
        except (ValueError, TypeError):
            continue

        note_date = _parse_date(note.get(date_label, ""))
        if not note_date:
            continue

        if bid not in bid_first_touch or note_date < bid_first_touch[bid]:
            bid_first_touch[bid] = note_date

    # Compute delta
    result = {}
    for bid, enroll_date in bid_enrollment_date.items():
        first_touch = bid_first_touch.get(bid)
        if first_touch and enroll_date:
            delta = (first_touch - enroll_date).days
            result[bid] = max(delta, 0)  # Clamp negatives to 0

    return result


def _detect_ob_sequence(territory_notes: list[dict], bid: str) -> dict:
    """
    Check which OB steps are logged for a BID.

    Returns:
        Dict with keys ob1, ob2, ob3, ob_final (bool each), plus
        call_count (int) and last_touch_date (str or None).
    """
    subject_label = COLUMN_LABELS.get("isr_note_subject", "_label_Subject")
    bid_label = COLUMN_LABELS.get("isr_note_branch_id", "Branch ID")
    date_label = COLUMN_LABELS.get("isr_note_date", "_label_Created Date")

    result = {
        "ob1": False,
        "ob2": False,
        "ob3": False,
        "ob_final": False,
        "call_count": 0,
        "last_touch_date": None,
    }

    latest_date = None

    for note in territory_notes:
        bid_raw = note.get(bid_label, "")
        try:
            note_bid = str(int(float(str(bid_raw))))
        except (ValueError, TypeError):
            continue

        if note_bid != bid:
            continue

        subject = str(note.get(subject_label, "")).strip()
        note_date = _parse_date(note.get(date_label, ""))

        if "OB1" in subject or "Welcome" in subject:
            result["ob1"] = True
        if "OB2" in subject or "Demo" in subject:
            result["ob2"] = True
        if "OB3" in subject or "Follow Up" in subject:
            result["ob3"] = True
        if "OB Final" in subject or "Final" in subject:
            result["ob_final"] = True
        if subject in ("Call", "OB1 Welcome", "OB2 Demo", "OB3 Follow Up", "OB Final"):
            result["call_count"] += 1

        if note_date:
            if latest_date is None or note_date > latest_date:
                latest_date = note_date

    if latest_date:
        result["last_touch_date"] = latest_date.isoformat()

    return result


def _extract_bid_funding(osr_cohorts: dict) -> dict:
    """
    Extract total funding per BID from cohort merchant lists.

    Returns:
        Dict mapping bid (str) -> total funded (float)
    """
    bid_funding = {}
    for entry in osr_cohorts.values():
        if not entry:
            continue
        for merch in entry.get("s", []):
            bid = str(merch.get("b", ""))
            total = merch.get("t2", 0.0)
            bid_funding[bid] = total
    return bid_funding


def _get_rep_checkins(field_activity: dict, osr_name: str) -> int:
    """Get total field check-in stops for an OSR from field_activity data."""
    for rep in field_activity.get("repActivity", []):
        if rep.get("n") == osr_name:
            return rep.get("t", 0)
    return 0


def _derive_primary_isr(territory_notes: list[dict]) -> str:
    """Determine the primary ISR from note frequency."""
    rep_label = COLUMN_LABELS.get("isr_note_rep", "_label_Assigned")
    isr_counter = Counter()

    for note in territory_notes:
        isr = note.get(rep_label, "")
        if isr and isr in ISR_ROSTER:
            isr_counter[isr] += 1

    if isr_counter:
        return isr_counter.most_common(1)[0][0]
    return ""


def _find_first_touch_date(territory_notes: list[dict], bid: str) -> date | None:
    """Find the date of the first ISR note for a BID."""
    bid_label = COLUMN_LABELS.get("isr_note_branch_id", "Branch ID")
    date_label = COLUMN_LABELS.get("isr_note_date", "_label_Created Date")

    earliest = None
    for note in territory_notes:
        bid_raw = note.get(bid_label, "")
        try:
            note_bid = str(int(float(str(bid_raw))))
        except (ValueError, TypeError):
            continue
        if note_bid != bid:
            continue
        note_date = _parse_date(note.get(date_label, ""))
        if note_date and (earliest is None or note_date < earliest):
            earliest = note_date
    return earliest


def _get_note_field(note: dict, col_key: str) -> str:
    """Get a field from an ISR note row using COLUMN_LABELS mapping."""
    label = COLUMN_LABELS.get(col_key, col_key)
    return str(note.get(label, "")).strip()


def _compute_maturity(enrollment_month: int, year: int, today: date) -> str:
    """
    Determine cohort maturity stage.

    - "early": still in M0
    - "m1_active": in M1 window
    - "m2_active": in M2 true-up window
    - "closed": past M2
    """
    # End of enrollment month = end of M0
    if enrollment_month == 12:
        m1_start = date(year + 1, 1, 1)
    else:
        m1_start = date(year, enrollment_month + 1, 1)

    m1_month = m1_start.month
    m1_year = m1_start.year
    if m1_month == 12:
        m2_start = date(m1_year + 1, 1, 1)
    else:
        m2_start = date(m1_year, m1_month + 1, 1)

    m2_month = m2_start.month
    m2_year = m2_start.year
    if m2_month == 12:
        m2_end = date(m2_year + 1, 1, 1)
    else:
        m2_end = date(m2_year, m2_month + 1, 1)

    if today < m1_start:
        return "early"
    elif today < m2_start:
        return "m1_active"
    elif today < m2_end:
        return "m2_active"
    else:
        return "closed"


def _classify_producer_pattern(ob: dict) -> str:
    """Classify how a producing merchant was activated based on OB sequence."""
    has_ob1 = ob.get("ob1", False)
    has_ob2 = ob.get("ob2", False)
    has_ob3 = ob.get("ob3", False)
    has_final = ob.get("ob_final", False)

    if has_ob2 and has_final:
        return "Full OB sequence"
    elif has_ob2:
        return "Partial OB (demo completed)"
    elif has_ob1 and not has_ob2:
        return "OB1 only, no demo"
    elif ob.get("call_count", 0) > 0 and not has_ob1:
        return "Calls only (no OB sequence)"
    else:
        return "TSR-driven (no OB sequence)"


def _ob_summary_str(ob: dict) -> str:
    """Return a compact string summarizing OB progress."""
    steps = []
    if ob.get("ob1"):
        steps.append("OB1")
    if ob.get("ob2"):
        steps.append("OB2")
    if ob.get("ob3"):
        steps.append("OB3")
    if ob.get("ob_final"):
        steps.append("Final")
    if not steps:
        calls = ob.get("call_count", 0)
        if calls:
            return f"{calls} calls (no OB)"
        return "No ISR contact"
    return " > ".join(steps)


def _categorize_bid(funded, ob, days_since, enroll_date, merchant,
                    territory_notes, bid) -> tuple:
    """
    Assign a pipeline category to a BID.

    Returns:
        (category, reason, next_step) or (None, None, None) if no action needed
    """
    has_ob2 = ob.get("ob2", False)
    has_ob_final = ob.get("ob_final", False)
    call_count = ob.get("call_count", 0)

    # RETAIN: already producing well
    if funded > 5000:
        return (
            "RETAIN",
            f"Producing ${funded:,.0f}, active merchant",
            "Maintain relationship, check for growth opportunities",
        )

    # GROW: producing but under potential
    if 0 < funded <= 5000:
        return (
            "GROW",
            f"Producing ${funded:,.0f}, potential for more volume",
            "OB follow-up to increase usage" if not has_ob_final else "TSR visit to drive volume",
        )

    # Below here: zero funding
    if funded <= 0:
        # HIGH: OB sequence advanced, recent enrollment, zero funding
        if has_ob2 and days_since <= 60:
            return (
                "HIGH",
                f"OB2 done, enrolled {days_since}d ago, zero funding",
                "OB3/Final push this week" if not has_ob_final else "TSR follow-up to activate",
            )

        # ACT_NOW: enrolled > 30 days, zero funding, incomplete conditioning
        if days_since > 30 and not has_ob2:
            return (
                "ACT_NOW",
                f"Enrolled {days_since}d ago, zero funding, conditioning incomplete",
                "Restart OB sequence immediately" if call_count == 0 else "Escalate to OB2 Demo",
            )

        # HIGH: recently enrolled (< 30 days), has some ISR contact
        if days_since <= 30 and call_count > 0:
            return (
                "HIGH",
                f"New enrollment ({days_since}d), ISR engaged, awaiting first transaction",
                "Continue OB sequence on schedule",
            )

        # ACT_NOW: no contact at all
        if call_count == 0 and days_since > 3:
            return (
                "ACT_NOW",
                f"Enrolled {days_since}d ago, zero ISR contact, zero funding",
                "OB1 Welcome call ASAP",
            )

    return (None, None, None)


def _format_short_date(d: date | None) -> str:
    """Format a date as 'M/D' without zero-padding (cross-platform)."""
    if not d:
        return "N/A"
    return f"{d.month}/{d.day}"


def _try_int(val):
    """Try to convert to int, return as-is if not possible."""
    try:
        return int(float(str(val)))
    except (ValueError, TypeError):
        return val
