"""
Per-rep cohort email module.

Generates one JSON envelope per OSR with their personalized cohort status,
ready to be picked up by Power Automate and sent as an Outlook email.

Each envelope contains:
  - to:        rep email
  - subject:   summary line
  - html_body: Outlook-safe HTML email body

Cadence target: Monday 9 AM PST, run via Windows Task Scheduler.
Power Automate watches the OneDrive Outbox folder and sends each file.

Usage:
    py -m automation.cohort_emails --test
        Writes one envelope addressed to Kevin using sample data.
        For iterating on the email design without touching real data.

    py -m automation.cohort_emails --from-html
        Reads cohort data from cohort-tracking.html and writes
        one envelope per rep on the roster.

    py -m automation.cohort_emails --from-html --rep "Cesar Flores"
        Single rep dry-run.

    py -m automation.cohort_emails --from-html --out ./output
        Override outbox directory (default: COHORT_EMAIL_OUTBOX in config.py).
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from html import escape

from .config import (
    OSR_ROSTER,
    OSR_EMAILS,
    TERRITORY_MAP,
    MONTH_ABBREV,
    MONTH_NAMES,
    COHORT_TARGET_M1,
    COHORT_TARGET_M2,
    COHORT_EMAIL_OUTBOX,
    COHORT_EMAIL_ADMIN,
    PROJECT_ROOT,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── Date helpers ────────────────────────────────────────────────────────────

def end_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def business_days_between(start: date, end: date) -> int:
    """Inclusive count of weekdays from start through end."""
    if end < start:
        return 0
    days = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:  # Mon-Fri
            days += 1
        cur += timedelta(days=1)
    return days


def first_name(full_name: str) -> str:
    return full_name.strip().split(" ")[0] if full_name else "there"


# ─── Cohort selection ────────────────────────────────────────────────────────

def strip_territory(display_name: str) -> str:
    """'Cesar Flores (RIC-1)' → 'Cesar Flores'"""
    return re.sub(r"\s*\([^)]+\)\s*$", "", display_name).strip()


def find_rep_entry(cohort: list[dict], rep_name: str) -> dict | None:
    """Find a rep's entry in a cohort list. Matches on the bare name."""
    if not cohort:
        return None
    target = rep_name.strip().lower()
    for entry in cohort:
        if strip_territory(entry.get("n", "")).lower() == target:
            return entry
    return None


# ─── Section builders ────────────────────────────────────────────────────────

def status_for_pct(pct: float) -> tuple[str, str, str]:
    """Return (label, bg color, text color on badge) for a target completion percentage."""
    if pct >= 100:
        return ("HIT", STATUS_HIT_BG, "#FFFFFF")
    if pct >= 75:
        return ("CLOSE", STATUS_CLOSE_BG, STATUS_CLOSE_TEXT)
    return ("BEHIND", STATUS_BEHIND_BG, "#FFFFFF")


def build_active_section(
    entry: dict | None,
    enroll_month: int,
    enroll_year: int,
    today: date,
) -> dict:
    """
    Active cohort = previous month's enrollees, currently in M1.
    The $15K deadline is the last day of the current calendar month.
    """
    m0_key = MONTH_ABBREV[enroll_month]
    m1_month = enroll_month + 1
    m1_year = enroll_year
    if m1_month > 12:
        m1_month -= 12
        m1_year += 1
    m1_key = MONTH_ABBREV[m1_month]
    m2_month = m1_month + 1
    m2_year = m1_year
    if m2_month > 12:
        m2_month -= 12
        m2_year += 1
    m2_key = MONTH_ABBREV[m2_month]

    deadline = end_of_month(m1_year, m1_month)
    days_remaining = business_days_between(today, deadline)

    section = {
        "title": f"{MONTH_NAMES[enroll_month]} Cohort",
        "subtitle": f"$15K deadline: end of {MONTH_NAMES[m1_month]}",
        "deadline_str": deadline.strftime("%a %b %-d") if os.name != "nt" else deadline.strftime("%a %b %#d"),
        "days_remaining": days_remaining,
        "m0_label": MONTH_NAMES[enroll_month],
        "m1_label": MONTH_NAMES[m1_month],
        "m2_label": MONTH_NAMES[m2_month],
        "m0_key": m0_key,
        "m1_key": m1_key,
        "m2_key": m2_key,
        "has_data": entry is not None,
    }

    if not entry:
        section.update({
            "merchant_count": 0,
            "producing_count": 0,
            "funded_total": 0.0,
            "funded_m2": 0.0,
            "pct": 0,
            "gap": COHORT_TARGET_M1,
            "status_label": "NO ENROLLMENTS",
            "status_color": "#6B7280",
            "status_text_color": "#FFFFFF",
            "show_m2_trueup": False,
            "m2_pct": 0,
            "m2_gap": COHORT_TARGET_M2,
            "merchants": [],
            "m0_total": 0.0,
            "m1_total": 0.0,
            "m2_total": 0.0,
        })
        return section

    funded = float(entry.get("f", 0))
    funded_all = float(entry.get("f2", funded))
    pct = round(funded / COHORT_TARGET_M1 * 100) if COHORT_TARGET_M1 else 0
    gap = max(0.0, COHORT_TARGET_M1 - funded)
    label, color, badge_text_color = status_for_pct(pct)

    # M2 true-up only shown when M1 already missed AND we're past M1 month-end
    past_m1 = today > deadline
    show_m2 = past_m1 and funded < COHORT_TARGET_M1
    m2_pct = round(funded_all / COHORT_TARGET_M2 * 100) if COHORT_TARGET_M2 else 0
    m2_gap = max(0.0, COHORT_TARGET_M2 - funded_all)

    section.update({
        "merchant_count": int(entry.get("m", 0)),
        "producing_count": int(entry.get("p", 0)),
        "funded_total": funded,
        "funded_m2": funded_all,
        "pct": pct,
        "gap": gap,
        "status_label": label,
        "status_color": color,
        "status_text_color": badge_text_color,
        "show_m2_trueup": show_m2,
        "m2_pct": m2_pct,
        "m2_gap": m2_gap,
        "merchants": entry.get("s", []),
        "m0_total": float(entry.get(m0_key, 0)),
        "m1_total": float(entry.get(m1_key, 0)),
        "m2_total": float(entry.get(m2_key, 0)),
    })
    return section


def build_current_section(
    entry: dict | None,
    enroll_month: int,
    enroll_year: int,
    today: date,
) -> dict:
    """
    Current cohort = this month's enrollees, currently in M0.
    The $15K deadline is the last day of NEXT month.
    """
    m0_key = MONTH_ABBREV[enroll_month]
    m1_month = enroll_month + 1
    m1_year = enroll_year
    if m1_month > 12:
        m1_month -= 12
        m1_year += 1

    deadline = end_of_month(m1_year, m1_month)
    days_remaining = business_days_between(today, deadline)

    section = {
        "title": f"{MONTH_NAMES[enroll_month]} Cohort",
        "subtitle": "Currently building — first full month is next",
        "deadline_str": deadline.strftime("%a %b %-d") if os.name != "nt" else deadline.strftime("%a %b %#d"),
        "deadline_label": f"end of {MONTH_NAMES[m1_month]}",
        "days_remaining": days_remaining,
        "m0_label": MONTH_NAMES[enroll_month],
        "m1_label": MONTH_NAMES[m1_month],
        "m0_key": m0_key,
        "has_data": entry is not None and int(entry.get("m", 0)) > 0,
    }

    if not section["has_data"]:
        section.update({
            "merchant_count": 0,
            "producing_count": 0,
            "m0_funded": 0.0,
            "merchants": [],
        })
        return section

    section.update({
        "merchant_count": int(entry.get("m", 0)),
        "producing_count": int(entry.get("p", 0)),
        "m0_funded": float(entry.get(m0_key, 0)),
        "merchants": entry.get("s", []),
    })
    return section


# ─── Formatters ──────────────────────────────────────────────────────────────

def fmt_money(amount: float) -> str:
    if amount is None:
        return "$0"
    if abs(amount) >= 1000:
        return f"${amount/1000:.1f}K"
    return f"${int(round(amount))}"


def fmt_money_full(amount: float) -> str:
    return f"${int(round(amount or 0)):,}"


# ─── HTML rendering ──────────────────────────────────────────────────────────
# EasyPay Finance brand palette — see easypay-branding skill design system.

EMAIL_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif"

# Brand primaries
EP_BLUE = "#1F5577"
EP_BLUE_LIGHT = "#2A6B94"
EP_GREEN = "#1AC668"
EP_TEAL = "#1BCEAC"

# Surfaces
COLOR_BG_PAGE = "#F6F8FA"        # outer email background
COLOR_BG_CARD = "#F6F8FA"        # email card — same as page (no white inversion fight)
COLOR_BG_SECTION = "#F6F8FA"     # cohort section — borders define structure, not fill

# Text
COLOR_TEXT = "#2C3E50"           # body
COLOR_TEXT_MUTED = "#555555"
COLOR_TEXT_DIM = "#6B7280"

# Borders
COLOR_BORDER = "#D5DEE7"          # slightly stronger so it carries structure on flat bg
COLOR_BORDER_TABLE = "#D5DEE7"

# Status colors (cohort progress)
STATUS_HIT_BG = EP_GREEN
STATUS_CLOSE_BG = "#FFC107"      # brand gold
STATUS_CLOSE_TEXT = "#856404"
STATUS_BEHIND_BG = "#E74C3C"     # red — kept for clear "off track" signal

# Logo
LOGO_URL = "https://customerappx.easypayfinance.com/layout/images/EasyPay.png"


def render_progress_bar(pct: int, color: str, width_px: int = 484) -> str:
    """Outlook-safe progress bar using nested tables with bgcolor."""
    pct_clamped = max(0, min(100, pct))
    track_bg = "#E8EEF3"
    # When the badge color is the brand gold, use the darker gold text for legibility
    fill_text_color = STATUS_CLOSE_TEXT if color == STATUS_CLOSE_BG else "#FFFFFF"
    if pct_clamped == 0:
        return f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="{width_px}" style="border-collapse:collapse;background:{track_bg};border-radius:8px;width:{width_px}px"><tr><td bgcolor="{track_bg}" height="22" style="height:22px;line-height:22px;font-size:0;border-radius:8px">&nbsp;</td></tr></table>'''
    if pct_clamped >= 100:
        return f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="{width_px}" style="border-collapse:collapse;background:{color};border-radius:8px;width:{width_px}px"><tr><td bgcolor="{color}" height="22" style="height:22px;line-height:22px;font-size:11px;font-weight:700;color:{fill_text_color};text-align:center;border-radius:8px;font-family:{EMAIL_FONT}">{pct_clamped}% of target</td></tr></table>'''
    fill_w = max(2, int(width_px * pct_clamped / 100))
    rest_w = width_px - fill_w
    return f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="{width_px}" style="border-collapse:collapse;background:{track_bg};border-radius:8px;width:{width_px}px"><tr><td bgcolor="{color}" width="{fill_w}" height="22" style="background:{color};width:{fill_w}px;height:22px;line-height:22px;font-size:11px;font-weight:700;color:{fill_text_color};text-align:center;border-radius:8px 0 0 8px;font-family:{EMAIL_FONT};white-space:nowrap">{pct_clamped}%</td><td bgcolor="{track_bg}" width="{rest_w}" height="22" style="background:{track_bg};width:{rest_w}px;height:22px;line-height:22px;font-size:0;border-radius:0 8px 8px 0">&nbsp;</td></tr></table>'''


def render_merchant_table(
    merchants: list[dict],
    column_keys: list[str],
    column_labels: list[str],
    show_total: bool = True,
) -> str:
    """Render a merchant funding table. Outlook-friendly."""
    if not merchants:
        return f'<p style="margin:8px 0 0;font-size:13px;color:{COLOR_TEXT_MUTED};font-style:italic;font-family:{EMAIL_FONT}">No merchants in this cohort yet.</p>'

    # Header — EasyPay Blue header row, white text
    header_cells = [
        f'<td bgcolor="{EP_BLUE}" style="background:{EP_BLUE};padding:10px 12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#FFFFFF;font-family:{EMAIL_FONT};border-radius:6px 0 0 0">Merchant</td>'
    ]
    for i, label in enumerate(column_labels):
        is_last = (not show_total) and (i == len(column_labels) - 1)
        radius = ";border-radius:0 6px 0 0" if is_last else ""
        header_cells.append(
            f'<td bgcolor="{EP_BLUE}" align="right" style="background:{EP_BLUE};padding:10px 12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#FFFFFF;font-family:{EMAIL_FONT};white-space:nowrap{radius}">{escape(label)}</td>'
        )
    if show_total:
        header_cells.append(
            f'<td bgcolor="{EP_BLUE}" align="right" style="background:{EP_BLUE};padding:10px 12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#FFFFFF;font-family:{EMAIL_FONT};border-radius:0 6px 0 0">Total</td>'
        )

    rows = []
    # No alternating row backgrounds — they invert badly in Outlook dark mode.
    # Single transparent style means the row inherits whatever surrounds it,
    # which renders cleanly in both light and dark modes.
    for idx, m in enumerate(merchants):
        bg = COLOR_BG_CARD
        producing = float(m.get("t", 0)) > 0 or any(float(m.get(k, 0)) > 0 for k in column_keys)
        name = escape(str(m.get("n", "Unknown")))
        bid = m.get("b", "")
        name_cell = (
            f'<td bgcolor="{bg}" style="background:{bg};padding:11px 12px;font-size:13px;color:{COLOR_TEXT};font-family:{EMAIL_FONT};border-bottom:1px solid {COLOR_BORDER_TABLE}">'
            f'<div style="font-weight:600">{name}</div>'
            f'<div style="font-size:11px;color:{COLOR_TEXT_DIM};margin-top:2px">BID {escape(str(bid))}</div>'
            f'</td>'
        )
        cells = [name_cell]
        for k in column_keys:
            val = float(m.get(k, 0))
            display = fmt_money_full(val) if val > 0 else "&mdash;"
            color = COLOR_TEXT if val > 0 else COLOR_TEXT_DIM
            cells.append(
                f'<td bgcolor="{bg}" align="right" style="background:{bg};padding:11px 12px;font-size:13px;color:{color};font-family:{EMAIL_FONT};border-bottom:1px solid {COLOR_BORDER_TABLE};white-space:nowrap">{display}</td>'
            )
        if show_total:
            total = float(m.get("t", 0))
            t_color = EP_GREEN if producing else COLOR_TEXT_DIM
            cells.append(
                f'<td bgcolor="{bg}" align="right" style="background:{bg};padding:11px 12px;font-size:13px;font-weight:700;color:{t_color};font-family:{EMAIL_FONT};border-bottom:1px solid {COLOR_BORDER_TABLE};white-space:nowrap">{fmt_money_full(total)}</td>'
            )
        rows.append(f'<tr>{"".join(cells)}</tr>')

    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;width:100%;margin-top:12px">'
        f'<tr>{"".join(header_cells)}</tr>'
        f'{"".join(rows)}'
        f'</table>'
    )


def render_active_section_html(s: dict) -> str:
    if not s["has_data"]:
        return f'''
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;width:100%;margin-top:24px">
  <tr><td bgcolor="{COLOR_BG_SECTION}" style="background-color:{COLOR_BG_SECTION};border:1px solid {COLOR_BORDER};border-radius:10px;padding:24px 28px">
    <div style="font-size:18px;font-weight:700;color:{EP_BLUE};font-family:{EMAIL_FONT};margin-bottom:4px">{escape(s['title'])} — closing this month</div>
    <div style="font-size:12px;color:{COLOR_TEXT_DIM};font-family:{EMAIL_FONT};text-transform:uppercase;letter-spacing:.05em;margin-bottom:16px">{escape(s['subtitle'])}</div>
    <div style="font-size:15px;color:{COLOR_TEXT_MUTED};font-family:{EMAIL_FONT};line-height:1.55">No enrollments credited to you for {escape(s['m0_label'])} &mdash; no cohort to close this month.</div>
  </td></tr>
</table>'''

    pct = s["pct"]
    color = s["status_color"]
    badge_text = s["status_text_color"]
    label = s["status_label"]
    funded_str = fmt_money_full(s["funded_total"])
    target_str = "$15,000"
    gap_str = fmt_money_full(s["gap"]) if s["gap"] > 0 else None

    stat_block = f'''
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;width:100%;margin-bottom:14px">
  <tr>
    <td valign="middle" style="font-family:{EMAIL_FONT}">
      <div style="font-size:32px;font-weight:700;color:{EP_BLUE};line-height:1.1">{funded_str} <span style="font-size:18px;color:{COLOR_TEXT_MUTED};font-weight:500">/ {target_str}</span></div>
      <div style="font-size:14px;color:{COLOR_TEXT_MUTED};margin-top:4px;line-height:1.5">{pct}% of target &middot; {s['producing_count']} of {s['merchant_count']} merchants funding</div>
    </td>
    <td valign="middle" align="right" style="font-family:{EMAIL_FONT}">
      <span style="display:inline-block;background:{color};color:{badge_text};font-size:12px;font-weight:700;letter-spacing:.06em;padding:7px 16px;border-radius:16px">{label}</span>
    </td>
  </tr>
</table>'''

    progress_html = render_progress_bar(pct, color)

    if s["show_m2_trueup"]:
        gap_line = f'''<div style="font-size:14px;color:{COLOR_TEXT_MUTED};font-family:{EMAIL_FONT};margin-top:12px;line-height:1.55">M1 deadline closed &mdash; now in <strong style="color:{EP_BLUE}">Month 2 true-up</strong>: {fmt_money_full(s['funded_m2'])} of $30,000 ({s['m2_pct']}%) &middot; {fmt_money_full(s['m2_gap'])} gap</div>'''
    elif s["gap"] > 0:
        gap_line = f'''<div style="font-size:14px;color:{COLOR_TEXT_MUTED};font-family:{EMAIL_FONT};margin-top:12px;line-height:1.55">{gap_str} from target &middot; <strong style="color:{EP_BLUE}">{s['days_remaining']} business {"day" if s['days_remaining']==1 else "days"}</strong> left ({escape(s['deadline_str'])})</div>'''
    else:
        gap_line = f'''<div style="font-size:14px;color:{EP_GREEN};font-family:{EMAIL_FONT};margin-top:12px;font-weight:600;line-height:1.55">Target hit.</div>'''

    table_html = render_merchant_table(
        s["merchants"],
        column_keys=[s["m0_key"], s["m1_key"]],
        column_labels=[s["m0_label"], s["m1_label"]],
        show_total=True,
    )

    return f'''
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;width:100%;margin-top:24px">
  <tr><td bgcolor="{COLOR_BG_SECTION}" style="background-color:{COLOR_BG_SECTION};border:1px solid {COLOR_BORDER};border-radius:10px;padding:24px 28px">
    <div style="font-size:18px;font-weight:700;color:{EP_BLUE};font-family:{EMAIL_FONT};margin-bottom:2px">{escape(s['title'])} <span style="color:{COLOR_TEXT_MUTED};font-weight:500">&mdash; closing this month</span></div>
    <div style="font-size:12px;color:{COLOR_TEXT_DIM};font-family:{EMAIL_FONT};text-transform:uppercase;letter-spacing:.05em;margin-bottom:16px">{escape(s['subtitle'])}</div>
    {stat_block}
    {progress_html}
    {gap_line}
    {table_html}
  </td></tr>
</table>'''


def render_current_section_html(s: dict) -> str:
    if not s["has_data"]:
        return f'''
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;width:100%;margin-top:16px">
  <tr><td bgcolor="{COLOR_BG_SECTION}" style="background-color:{COLOR_BG_SECTION};border:1px solid {COLOR_BORDER};border-radius:10px;padding:24px 28px">
    <div style="font-size:18px;font-weight:700;color:{EP_BLUE};font-family:{EMAIL_FONT};margin-bottom:2px">{escape(s['title'])} <span style="color:{COLOR_TEXT_MUTED};font-weight:500">&mdash; currently building</span></div>
    <div style="font-size:12px;color:{COLOR_TEXT_DIM};font-family:{EMAIL_FONT};text-transform:uppercase;letter-spacing:.05em;margin-bottom:14px">$15K deadline {escape(s['deadline_label'])}</div>
    <div style="font-size:15px;color:{COLOR_TEXT_MUTED};font-family:{EMAIL_FONT};line-height:1.55">No enrollments yet this month. New enrollments will start showing here as soon as they're credited &mdash; {s['days_remaining']} business days until the {escape(s['m1_label'])} M1 deadline.</div>
  </td></tr>
</table>'''

    funded_str = fmt_money_full(s["m0_funded"])
    enrolled = s["merchant_count"]
    producing = s["producing_count"]

    stat_block = f'''
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;width:100%;margin-bottom:6px">
  <tr>
    <td valign="top" style="font-family:{EMAIL_FONT}" width="50%">
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:{COLOR_TEXT_DIM};margin-bottom:6px">Enrollments so far</div>
      <div style="font-size:28px;font-weight:700;color:{EP_BLUE};line-height:1">{enrolled} <span style="font-size:14px;color:{COLOR_TEXT_MUTED};font-weight:500">merchant{"" if enrolled==1 else "s"}</span></div>
      <div style="font-size:13px;color:{COLOR_TEXT_MUTED};margin-top:6px;line-height:1.5">{producing} already funding</div>
    </td>
    <td valign="top" align="right" style="font-family:{EMAIL_FONT}" width="50%">
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:{COLOR_TEXT_DIM};margin-bottom:6px">Early M0 Funded</div>
      <div style="font-size:28px;font-weight:700;color:{EP_GREEN};line-height:1">{funded_str}</div>
      <div style="font-size:13px;color:{COLOR_TEXT_MUTED};margin-top:6px;line-height:1.5">$15K target by {escape(s['deadline_label'])} &middot; {s['days_remaining']} business days</div>
    </td>
  </tr>
</table>'''

    table_html = render_merchant_table(
        s["merchants"],
        column_keys=[s["m0_key"]],
        column_labels=[s["m0_label"]],
        show_total=False,
    )

    return f'''
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;width:100%;margin-top:16px">
  <tr><td bgcolor="{COLOR_BG_SECTION}" style="background-color:{COLOR_BG_SECTION};border:1px solid {COLOR_BORDER};border-radius:10px;padding:24px 28px">
    <div style="font-size:18px;font-weight:700;color:{EP_BLUE};font-family:{EMAIL_FONT};margin-bottom:2px">{escape(s['title'])} <span style="color:{COLOR_TEXT_MUTED};font-weight:500">&mdash; currently building</span></div>
    <div style="font-size:12px;color:{COLOR_TEXT_DIM};font-family:{EMAIL_FONT};text-transform:uppercase;letter-spacing:.05em;margin-bottom:16px">$15K deadline {escape(s['deadline_label'])}</div>
    {stat_block}
    {table_html}
  </td></tr>
</table>'''


def render_email_html(rep_name: str, today: date, active: dict, current: dict) -> str:
    fname = first_name(rep_name)
    today_str = today.strftime("%a %b %-d") if os.name != "nt" else today.strftime("%a %b %#d")

    active_html = render_active_section_html(active)
    current_html = render_current_section_html(current)

    return f'''<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>Cohort Update</title>
<style type="text/css">
  :root {{ color-scheme: light; supported-color-schemes: light; }}
  /* Outlook.com dark mode override */
  [data-ogsc] body, [data-ogsb] body {{ background-color: {COLOR_BG_PAGE} !important; }}
  [data-ogsc] td, [data-ogsc] div, [data-ogsc] span, [data-ogsc] p, [data-ogsc] h1 {{ color: inherit !important; }}
</style>
<body bgcolor="{COLOR_BG_PAGE}" style="margin:0;padding:0;background-color:{COLOR_BG_PAGE};font-family:{EMAIL_FONT};color:{COLOR_TEXT}">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" bgcolor="{COLOR_BG_PAGE}" style="min-width:100%;background-color:{COLOR_BG_PAGE}">
<tr><td align="center" valign="top" bgcolor="{COLOR_BG_PAGE}" style="padding:24px 10px;background-color:{COLOR_BG_PAGE}">

<table role="presentation" align="center" border="0" cellpadding="0" cellspacing="0" width="600" bgcolor="{COLOR_BG_CARD}" style="max-width:600px;background-color:{COLOR_BG_CARD};border-collapse:separate">

  <!-- Header: blue gradient + logo + headline -->
  <tr><td style="padding:0">
    <!--[if mso]>
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%"><tr><td bgcolor="{EP_BLUE}" style="background-color:{EP_BLUE};padding:30px 30px 26px;text-align:center;border-radius:12px 12px 0 0">
    <![endif]-->
    <!--[if !mso]><!-->
    <div style="background:linear-gradient(135deg,{EP_BLUE} 0%,{EP_BLUE_LIGHT} 100%);background-color:{EP_BLUE};border-radius:12px 12px 0 0;padding:30px 30px 26px;text-align:center">
    <!--<![endif]-->
      <div style="margin-bottom:16px">
        <img src="{LOGO_URL}" alt="EasyPay Finance" width="180" style="display:block;max-width:180px;margin:0 auto;border:0;outline:none;text-decoration:none">
      </div>
      <div style="font-size:11px;font-weight:700;color:{EP_TEAL};letter-spacing:.12em;text-transform:uppercase;font-family:{EMAIL_FONT};margin-bottom:6px">Weekly Cohort Update</div>
      <h1 style="font-size:24px;font-weight:700;margin:0;line-height:1.3;color:#FFFFFF;font-family:{EMAIL_FONT}">Week of {escape(today_str)}</h1>
    <!--[if !mso]><!-->
    </div>
    <!--<![endif]-->
    <!--[if mso]>
    </td></tr></table>
    <![endif]-->
  </td></tr>

  <!-- Greeting -->
  <tr><td bgcolor="{COLOR_BG_CARD}" style="padding:30px 30px 4px;background-color:{COLOR_BG_CARD};font-family:{EMAIL_FONT}">
    <p style="margin:0;font-size:16px;color:{COLOR_TEXT};line-height:1.55">
      Hi {escape(fname)},
    </p>
    <p style="margin:10px 0 0;font-size:15px;color:{COLOR_TEXT_MUTED};line-height:1.6">
      Here's your weekly look at both cohorts &mdash; the one closing for commission this month, and the one you're currently building.
    </p>
  </td></tr>

  <!-- Cohort sections -->
  <tr><td bgcolor="{COLOR_BG_CARD}" style="padding:0 30px;background-color:{COLOR_BG_CARD}">
    {active_html}
    {current_html}
  </td></tr>

  <!-- Sign-off (no consumer footer for internal team email) -->
  <tr><td bgcolor="{COLOR_BG_CARD}" style="padding:28px 30px 32px;background-color:{COLOR_BG_CARD};font-family:{EMAIL_FONT}">
    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-top:1px solid {COLOR_BORDER}">
      <tr><td style="padding-top:18px;font-size:14px;color:{COLOR_TEXT_MUTED};line-height:1.6;font-family:{EMAIL_FONT}">
        Let me know if you have any questions.
      </td></tr>
      <tr><td style="padding-top:14px;font-family:{EMAIL_FONT}">
        <p style="margin:0;color:{COLOR_TEXT_MUTED};font-size:14px">Best,</p>
        <p style="margin:4px 0 0;color:{EP_BLUE};font-size:15px;font-weight:700">Kevin Villegas <span style="color:{COLOR_TEXT_DIM};font-weight:500">&middot; Sales Program Manager</span></p>
      </td></tr>
    </table>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>'''


# ─── Subject line ────────────────────────────────────────────────────────────

def build_subject(active: dict, current: dict, today: date) -> str:
    today_str = today.strftime("%b %-d") if os.name != "nt" else today.strftime("%b %#d")
    if active["has_data"]:
        funded = fmt_money(active["funded_total"])
        return f"{active['title']}: {funded} / $15K · cohort update {today_str}"
    if current["has_data"]:
        return f"{current['title']} tracking · cohort update {today_str}"
    return f"Cohort update {today_str}"


# ─── Envelope assembly ───────────────────────────────────────────────────────

def build_envelope(
    rep_name: str,
    rep_email: str,
    active_cohort_list: list[dict],
    current_cohort_list: list[dict],
    active_enroll_month: int,
    active_enroll_year: int,
    current_enroll_month: int,
    current_enroll_year: int,
    today: date,
) -> dict | None:
    """
    Returns {to, subject, html_body, _meta} or None if rep should be skipped.
    """
    active_entry = find_rep_entry(active_cohort_list, rep_name)
    current_entry = find_rep_entry(current_cohort_list, rep_name)
    # Always generate an envelope — even with no enrollments in either cohort.
    # The empty-state messaging keeps reps engaged and reinforces the weekly cadence.

    active = build_active_section(active_entry, active_enroll_month, active_enroll_year, today)
    current = build_current_section(current_entry, current_enroll_month, current_enroll_year, today)

    html_body = render_email_html(rep_name, today, active, current)
    subject = build_subject(active, current, today)

    return {
        "to": rep_email,
        "subject": subject,
        "html_body": html_body,
        "_meta": {
            "rep_name": rep_name,
            "send_date": today.isoformat(),
            "active_cohort": f"{MONTH_ABBREV[active_enroll_month]}-{active_enroll_year}",
            "current_cohort": f"{MONTH_ABBREV[current_enroll_month]}-{current_enroll_year}",
            "active_funded": active.get("funded_total", 0),
            "active_pct": active.get("pct", 0),
            "current_enrolled": current.get("merchant_count", 0),
        },
    }


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def write_envelope(envelope: dict, outbox_dir: str, today: date) -> str:
    os.makedirs(outbox_dir, exist_ok=True)
    rep = envelope["_meta"]["rep_name"]
    fname = f"{today.isoformat()}_{slugify(rep)}.json"
    path = os.path.join(outbox_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2, ensure_ascii=False)
    return path


# ─── Cohort data sources ─────────────────────────────────────────────────────

def pull_latest():
    """Pull latest dashboard data from GitHub into the local checkout.

    The hourly pipeline runs in GitHub Actions and commits cohort-tracking.html
    to GitHub — it does not auto-sync to this machine. Without a `git pull`
    here, we'd read stale local data and send emails with old numbers.
    Failures are logged but non-fatal; the script falls back to whatever's
    already on disk.
    """
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            msg = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "up to date"
            logger.info("git pull: %s", msg)
        else:
            logger.warning("git pull failed (using local data): %s",
                           result.stderr.strip() or result.stdout.strip())
    except Exception as e:
        logger.warning("git pull errored (using local data): %s", e)


def load_cohorts_from_html(html_path: str) -> dict[str, list[dict]]:
    """
    Parse cohort variables out of cohort-tracking.html.

    Returns dict like {"aprCohort": [...], "mayCohort": [...], ...}.
    """
    if not os.path.exists(html_path):
        raise FileNotFoundError(html_path)
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    cohorts = {}
    # Match: var aprCohort = [ ... ];
    pattern = re.compile(
        r"var\s+(\w+Cohort)\s*=\s*(\[.*?\]);",
        re.DOTALL,
    )
    for match in pattern.finditer(content):
        var_name = match.group(1)
        js_array = match.group(2)
        try:
            data = json.loads(js_array)
            cohorts[var_name] = data
        except json.JSONDecodeError as e:
            logger.warning("Could not parse %s: %s", var_name, e)
    return cohorts


def cohort_var_for(month: int) -> str:
    return f"{MONTH_ABBREV[month]}Cohort"


# ─── Sample data for --test mode ─────────────────────────────────────────────

def sample_cohorts() -> tuple[list[dict], list[dict]]:
    """Two-rep sample to exercise the full layout: one behind, one with no current cohort."""
    apr = [
        {
            "n": "Cesar Flores (RIC-1)",
            "m": 5, "p": 3,
            "f": 12400.0, "f2": 14200.0,
            "apr": 4200.0, "may": 8200.0, "jun": 1800.0,
            "s": [
                {"n": "ABC Auto Repair", "b": 12345, "apr": 4200, "may": 8200, "jun": 0, "t": 12400, "t2": 12400},
                {"n": "Quick Tire Co", "b": 12346, "apr": 0, "may": 0, "jun": 1800, "t": 0, "t2": 1800},
                {"n": "Premier Mufflers", "b": 12347, "apr": 0, "may": 0, "jun": 0, "t": 0, "t2": 0},
                {"n": "El Sol Furniture", "b": 12348, "apr": 0, "may": 0, "jun": 0, "t": 0, "t2": 0},
                {"n": "Northgate Wheel & Tire", "b": 12349, "apr": 0, "may": 0, "jun": 0, "t": 0, "t2": 0},
            ],
        },
    ]
    may = [
        {
            "n": "Cesar Flores (RIC-1)",
            "m": 3, "p": 1,
            "f": 1800.0, "f2": 1800.0,
            "may": 1800.0, "jun": 0.0, "jul": 0.0,
            "s": [
                {"n": "Sunrise Detailing", "b": 12350, "may": 1800, "jun": 0, "jul": 0, "t": 1800, "t2": 1800},
                {"n": "Westside Audio", "b": 12351, "may": 0, "jun": 0, "jul": 0, "t": 0, "t2": 0},
                {"n": "Valley Brake & Lube", "b": 12352, "may": 0, "jun": 0, "jul": 0, "t": 0, "t2": 0},
            ],
        },
    ]
    return apr, may


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate per-rep cohort email envelopes.")
    parser.add_argument("--test", action="store_true",
                        help="Use sample data and write one envelope addressed to Kevin.")
    parser.add_argument("--from-html", action="store_true",
                        help="Read cohort data from cohort-tracking.html.")
    parser.add_argument("--rep", default=None,
                        help="Only generate envelope for this rep (full name).")
    parser.add_argument("--out", default=None,
                        help="Output directory (default: COHORT_EMAIL_OUTBOX from config).")
    parser.add_argument("--date", default=None,
                        help="Override send date as YYYY-MM-DD (default: today).")
    args = parser.parse_args()

    today = date.fromisoformat(args.date) if args.date else date.today()
    outbox = args.out or COHORT_EMAIL_OUTBOX

    # Determine cohort months from today.
    current_month = today.month
    current_year = today.year
    active_month = current_month - 1
    active_year = current_year
    if active_month < 1:
        active_month += 12
        active_year -= 1

    # ── Test mode ────────────────────────────────────────────────────────
    if args.test:
        logger.info("TEST MODE — using sample data, sending to %s", COHORT_EMAIL_ADMIN)
        active_list, current_list = sample_cohorts()
        envelope = build_envelope(
            rep_name="Cesar Flores",
            rep_email=COHORT_EMAIL_ADMIN,
            active_cohort_list=active_list,
            current_cohort_list=current_list,
            active_enroll_month=active_month,
            active_enroll_year=active_year,
            current_enroll_month=current_month,
            current_enroll_year=current_year,
            today=today,
        )
        if envelope is None:
            logger.error("Test envelope generation returned None — bug.")
            sys.exit(1)
        # Add a [TEST] tag to the subject so it can't be confused with real sends.
        envelope["subject"] = f"[TEST] {envelope['subject']}"
        envelope["_meta"]["test"] = True
        path = write_envelope(envelope, outbox, today)
        logger.info("Wrote test envelope: %s", path)
        # Only write the standalone .html preview when output is a local
        # directory — never write it into a OneDrive folder (it would also
        # trigger the Power Automate flow and cause a parse failure).
        if "OneDrive" not in os.path.abspath(outbox):
            html_path = path.replace(".json", ".preview.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(envelope["html_body"])
            logger.info("Browser preview: %s", html_path)
        return

    # ── Real-data mode ───────────────────────────────────────────────────
    if not args.from_html:
        logger.error("No data source specified. Use --test for sample data or --from-html for live data.")
        sys.exit(2)

    pull_latest()

    html_path = os.path.join(PROJECT_ROOT, "cohort-tracking.html")
    cohorts = load_cohorts_from_html(html_path)

    active_var = cohort_var_for(active_month)
    current_var = cohort_var_for(current_month)
    active_list = cohorts.get(active_var, [])
    current_list = cohorts.get(current_var, [])

    if not active_list and not current_list:
        logger.error("No cohort data found in HTML (looked for %s and %s). Has the pipeline run?",
                     active_var, current_var)
        sys.exit(3)

    logger.info("Loaded cohorts: active=%s (%d reps), current=%s (%d reps)",
                active_var, len(active_list), current_var, len(current_list))

    # Decide which reps to process
    if args.rep:
        targets = [args.rep]
    else:
        targets = list(OSR_ROSTER)

    written = 0
    skipped = 0
    for rep_name in targets:
        rep_email = OSR_EMAILS.get(rep_name, "")
        if not rep_email:
            logger.info("Skipping %s — no email configured", rep_name)
            skipped += 1
            continue

        envelope = build_envelope(
            rep_name=rep_name,
            rep_email=rep_email,
            active_cohort_list=active_list,
            current_cohort_list=current_list,
            active_enroll_month=active_month,
            active_enroll_year=active_year,
            current_enroll_month=current_month,
            current_enroll_year=current_year,
            today=today,
        )
        if envelope is None:
            skipped += 1
            continue

        path = write_envelope(envelope, outbox, today)
        logger.info("Wrote envelope for %s → %s", rep_name, path)
        written += 1

    logger.info("Done. %d envelopes written, %d reps skipped.", written, skipped)


if __name__ == "__main__":
    main()
