"""
Hybrid-role rep tracker processor.

Builds the data behind the index-page Hybrid Role Tracker widget for reps
working a mixed inside/outside role (HYBRID_REPS in config.py — currently
Marco Garmendia, RIC-10).

Sources:
- Report 7 (ISR Notes): the rep's Salesforce notes, filtered by _label_ISR
  and the current month (Report 7 spans the whole quarter).
- Report 5 (Maps check-ins): reuses the already-deduped per-rep stop list
  produced by the field_activity processor (repStops), so counts match the
  field-activity page exactly.
- Genesys talk time: matched by exact name; None until the rep is set up
  in Genesys (the widget renders a "pending setup" state).
"""

import logging
from collections import defaultdict
from datetime import date

from ..config import COLUMN_LABELS
from .field_activity import _parse_time_to_24h

logger = logging.getLogger(__name__)

DOW_NAMES = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

TOP_MERCHANTS_LIMIT = 8  # merchants shown in the card's Top Merchants table


def process(rep_name: str, territory: str, isr_notes: list[dict],
            field_result: dict, genesys_data: list[dict],
            month: int, year: int) -> dict:
    """
    Build the Hybrid Role Tracker card data for one rep.

    Args:
        rep_name: Rep name as it appears in Salesforce / Genesys.
        territory: Territory code shown next to the name (e.g. "RIC-10").
        isr_notes: Raw Report 7 rows (whole quarter).
        field_result: Output of field_activity.process() for the current month.
        genesys_data: Agent list from Genesys (name/talk_seconds/talk_display/calls).
        month, year: Current calendar month being tracked.

    Returns:
        Dict consumed by html_generator._generate_hybrid_tracker_html().
    """
    # ── Notes (Report 7, this month, attributed to the rep) ──────────────
    isr_label = COLUMN_LABELS.get("isr_note_rep", "_label_ISR")
    author_label = COLUMN_LABELS.get("isr_note_author", "_label_Created By")
    subject_label = COLUMN_LABELS.get("isr_note_subject", "_label_Subject")
    account_label = COLUMN_LABELS.get("isr_note_account", "_label_Account Name")
    bid_label = COLUMN_LABELS.get("isr_note_branch_id", "Branch ID")
    comment_label = COLUMN_LABELS.get("isr_note_comments", "_label_Full Comments")
    date_label = COLUMN_LABELS.get("isr_note_date", "_label_Created Date")

    notes = []
    for row in isr_notes:
        # Match by note author (Created By) — the ISR column is the ACCOUNT's
        # assigned ISR, not who wrote the note, so it can't attribute a hybrid
        # rep's own notes (and would over-count once the rep is assigned as
        # account ISR). Fall back to the ISR column only if the report ever
        # loses the Created By column.
        if author_label in row:
            if row.get(author_label) != rep_name:
                continue
        elif row.get(isr_label) != rep_name:
            continue
        note_date = _parse_mdy(row.get(date_label, ""))
        if note_date is None or note_date.month != month or note_date.year != year:
            continue
        comment = (row.get(comment_label) or "").strip()
        if comment == "-":
            comment = ""
        # Skip open/unlogged tasks (call-back and follow-up reminders that
        # haven't happened yet). Report 7 has no task-status column, but
        # logged calls and completed notes always carry comment text while
        # open tasks come through blank — only completed activity counts.
        if not comment:
            continue
        merchant = row.get(account_label) or row.get("_label_Company / Account") or ""
        notes.append({
            "date": note_date,
            "merchant": "" if merchant == "-" else merchant,
            "bid": str(row.get("_label_" + bid_label, row.get(bid_label, "")) or ""),
            "subject": row.get(subject_label, "") or "",
            "comment": comment,
        })

    note_merchants = {n["bid"] if n["bid"] not in ("", "-") else n["merchant"]
                      for n in notes if n["merchant"] or n["bid"] not in ("", "-")}
    note_days = {n["date"] for n in notes}

    # ── Field check-ins (already deduped by field_activity.process) ──────
    stops = []
    for stop in (field_result or {}).get("repStops", {}).get(rep_name, []):
        stop_date = _parse_mdy(stop.get("d", ""))
        if stop_date is None:
            continue
        stops.append({
            "date": stop_date,
            "time": stop.get("t", ""),
            "merchant": stop.get("n", ""),
            "existing": bool(stop.get("ex")),
            "comment": _strip_maps_prefix(stop.get("c", "")),
        })

    stop_days = {s["date"] for s in stops}
    stops_prospect = sum(1 for s in stops if not s["existing"])

    # ── Genesys (may not exist yet — widget shows pending state) ─────────
    genesys = next((g for g in (genesys_data or []) if g.get("name") == rep_name), None)

    # ── Daily breakdown (notes + check-ins per active day) ───────────────
    daily_map = defaultdict(lambda: {"notes": 0, "stops": 0})
    for n in notes:
        daily_map[n["date"]]["notes"] += 1
    for s in stops:
        daily_map[s["date"]]["stops"] += 1

    daily = [
        {
            "d": f"{d.month}/{d.day}",
            "dow": DOW_NAMES.get(d.weekday(), ""),
            "notes": counts["notes"],
            "stops": counts["stops"],
        }
        for d, counts in sorted(daily_map.items(), reverse=True)
    ]

    # ── Top merchants (notes + stops merged by merchant name) ────────────
    merch_map = {}
    for n in notes:
        name = n["merchant"] or "—"
        m = merch_map.setdefault(name.lower(), {
            "merchant": name, "bid": "", "notes": 0, "stops": 0, "last": n["date"]})
        m["notes"] += 1
        if n["date"] > m["last"]:
            m["last"] = n["date"]
        if n["bid"] and n["bid"] != "-" and not m["bid"]:
            m["bid"] = n["bid"]
    for s in stops:
        name = s["merchant"] or "—"
        m = merch_map.setdefault(name.lower(), {
            "merchant": name, "bid": "", "notes": 0, "stops": 0, "last": s["date"]})
        m["stops"] += 1
        if s["date"] > m["last"]:
            m["last"] = s["date"]

    ranked = sorted(merch_map.values(),
                    key=lambda m: (m["notes"] + m["stops"], m["last"]), reverse=True)
    top_merchants = [
        {"merchant": m["merchant"], "bid": m["bid"], "notes": m["notes"],
         "stops": m["stops"], "last": f"{m['last'].month}/{m['last'].day}"}
        for m in ranked[:TOP_MERCHANTS_LIMIT]
    ]
    more_merchants = max(len(ranked) - TOP_MERCHANTS_LIMIT, 0)

    # ── Full entry list for the hybrid-activity.html drill-down page ─────
    entries = []
    for n in notes:
        entries.append({
            "d": f"{n['date'].month}/{n['date'].day}",
            "dow": DOW_NAMES.get(n["date"].weekday(), ""),
            "iso": n["date"].isoformat(),
            "t": "",
            "type": "note",
            "merchant": n["merchant"] or "—",
            "bid": "" if n["bid"] == "-" else n["bid"],
            "subject": n["subject"],
            "comment": n["comment"],
        })
    for s in stops:
        entries.append({
            "d": f"{s['date'].month}/{s['date'].day}",
            "dow": DOW_NAMES.get(s["date"].weekday(), ""),
            "iso": s["date"].isoformat(),
            "t": s["time"],
            "type": "stop",
            "merchant": s["merchant"] or "—",
            "bid": "",
            "subject": "Existing merchant" if s["existing"] else "Prospect",
            "comment": s["comment"],
        })
    entries.sort(key=lambda e: (e["iso"], _parse_time_to_24h(e["t"]) if e["t"] else "00:00"),
                 reverse=True)

    logger.info(
        "Hybrid tracker %s: %d notes (%d merchants), %d check-ins, genesys=%s",
        rep_name, len(notes), len(note_merchants), len(stops),
        "yes" if genesys else "pending",
    )

    return {
        "name": rep_name,
        "territory": territory,
        "notes_total": len(notes),
        "notes_merchants": len(note_merchants),
        "notes_days": len(note_days),
        "stops_total": len(stops),
        "stops_prospect": stops_prospect,
        "stops_existing": len(stops) - stops_prospect,
        "stops_days": len(stop_days),
        "active_days": len(note_days | stop_days),
        "genesys": genesys,
        "daily": daily,
        "top_merchants": top_merchants,
        "more_merchants": more_merchants,
        "entries": entries,
    }


def _parse_mdy(val) -> date | None:
    """Parse 'M/D/YYYY' (Salesforce _label_ display format) into a date."""
    if not val:
        return None
    try:
        parts = str(val).strip().split("/")
        if len(parts) == 3:
            return date(int(parts[2]), int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        pass
    return None


def _strip_maps_prefix(comment: str) -> str:
    """Drop the boilerplate 'Checked in via Maps Application' first line."""
    if not comment:
        return ""
    lines = [ln.strip() for ln in comment.splitlines()]
    lines = [ln for ln in lines if ln and "checked in via maps" not in ln.lower()]
    return " ".join(lines)
