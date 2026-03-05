"""
Main orchestrator for the OSR Dashboard automation pipeline.

Flow: Authenticate → Fetch reports → Process data → Generate HTML → Done.

Usage:
    python -m automation.main              # Full run (updates HTML files in place)
    python -m automation.main --dry-run    # Outputs to output/ dir instead
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import date, timedelta

from .config import (
    SF_LOGIN_URL, SF_CLIENT_ID, SF_CLIENT_SECRET,
    REPORT_IDS, MONTH_ABBREV, MONTH_NAMES, PROJECT_ROOT,
    COLUMN_LABELS, month_filename, month_filepath,
)
from .salesforce_auth import SalesforceClient, SalesforceAuthError
from .salesforce_reports import fetch_all_reports, fetch_cohort_activity, parse_report_rows, fetch_report
from .processors import monthly_dashboard, cohort_tracking, q1_enrollment, field_activity, index_page
from . import html_generator

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="OSR Dashboard Automation")
    parser.add_argument("--dry-run", action="store_true",
                        help="Output to output/ dir instead of overwriting HTML files")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip Salesforce fetch (use cached data from data/snapshots/)")
    args = parser.parse_args()

    today = date.today()
    current_month = today.month
    current_year = today.year
    logger.info("=== OSR Dashboard Update - %s ===", today.isoformat())
    logger.info("Current month: %s %d", MONTH_NAMES[current_month], current_year)

    # ── Output directory ─────────────────────────────────────────────────
    if args.dry_run:
        output_dir = os.path.join(PROJECT_ROOT, "output")
        os.makedirs(output_dir, exist_ok=True)
        logger.info("DRY RUN: Output will go to %s", output_dir)
    else:
        output_dir = PROJECT_ROOT

    # ── Step 1: Authenticate ─────────────────────────────────────────────
    if not args.skip_fetch:
        if not SF_CLIENT_ID or not SF_CLIENT_SECRET:
            logger.error("Missing SF_CLIENT_ID or SF_CLIENT_SECRET environment variables.")
            sys.exit(1)

        client = SalesforceClient(SF_LOGIN_URL, SF_CLIENT_ID, SF_CLIENT_SECRET)
        try:
            client.authenticate()
        except SalesforceAuthError as e:
            logger.error("Authentication failed: %s", e)
            sys.exit(1)
    else:
        client = None
        logger.info("Skipping Salesforce fetch (--skip-fetch)")

    # ── Step 2: Fetch Reports ────────────────────────────────────────────
    if client:
        logger.info("--- Fetching core reports ---")
        try:
            reports = fetch_all_reports(client)
        except Exception as e:
            logger.error("Failed to fetch reports: %s", e)
            sys.exit(1)

        # Save snapshots
        snapshot_dir = os.path.join(PROJECT_ROOT, "data", "snapshots",
                                    f"{current_year}-{current_month:02d}")
        os.makedirs(snapshot_dir, exist_ok=True)
        for key, rows in reports.items():
            snapshot_path = os.path.join(snapshot_dir, f"{key}.json")
            with open(snapshot_path, "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2, default=str)
            logger.info("Saved snapshot: %s (%d rows)", snapshot_path, len(rows))
    else:
        # Load from latest snapshot
        reports = _load_latest_snapshot()

    # ── Step 3: Process Monthly Dashboard ────────────────────────────────
    logger.info("--- Processing monthly dashboard ---")
    monthly_data = monthly_dashboard.process(
        all_enrollments=reports.get("new_enrollments", []),
        credited_enrollments=reports.get("credited_enrollments", []),
        current_month_activity=reports.get("current_month_activity", []),
        last_month_activity=reports.get("last_month_activity", []),
        month=current_month,
        year=current_year,
    )

    # Update or create the monthly dashboard HTML
    month_file = month_filename(current_month, current_year)
    month_path = os.path.join(output_dir, month_file)

    # If this month's file doesn't exist, we need to create it from template
    if not os.path.exists(month_path):
        logger.info("Monthly file %s doesn't exist. Creating from previous month template.", month_file)
        _create_month_from_template(month_path, current_month, current_year)

    if os.path.exists(month_path):
        html_generator.update_monthly_dashboard(month_path, monthly_data)
    else:
        logger.warning("Could not create or find %s. Skipping monthly dashboard update.", month_file)

    # ── Step 4: Process Cohort Tracking ──────────────────────────────────
    logger.info("--- Processing cohort tracking ---")
    cohorts = {}
    cohort_kpis_dict = {}

    # Determine active cohorts
    # Active cohort: previous month's enrollees (their M1 is current month)
    prev_month = current_month - 1
    prev_year = current_year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1

    # Fetch cohort-specific activity data
    active_cohort_activity = {}
    if client:
        # M0 activity (enrollment month)
        m0_abbrev = MONTH_ABBREV[prev_month]
        active_cohort_activity[m0_abbrev] = reports.get("credited_enrollments", [])

        # M1 activity (current month) — need to fetch with date override
        m1_abbrev = MONTH_ABBREV[current_month]
        try:
            m1_rows = fetch_cohort_activity(
                client, prev_month, prev_year, current_month, current_year
            )
            active_cohort_activity[m1_abbrev] = m1_rows
        except Exception as e:
            logger.warning("Failed to fetch M1 cohort activity: %s", e)
            active_cohort_activity[m1_abbrev] = []

    # Build active cohort (previous month's enrollees)
    active_cohort_enrollments = reports.get("credited_enrollments", [])
    if active_cohort_enrollments:
        active_var_name = f"{MONTH_ABBREV[prev_month]}Cohort"
        active_cohort = cohort_tracking.process_cohort(
            credited_enrollments=active_cohort_enrollments,
            monthly_activity=active_cohort_activity,
            enrollment_month=prev_month,
            enrollment_year=prev_year,
        )
        cohorts[active_var_name] = active_cohort
        cohort_kpis_dict["active_cohort"] = cohort_tracking.compute_cohort_kpis(
            active_cohort, prev_month
        )

    # Build cohort configs for all tracked cohorts
    cohort_configs = _build_cohort_configs(current_month, current_year)

    # Update cohort-tracking.html
    cohort_path = os.path.join(output_dir, "cohort-tracking.html")
    if os.path.exists(cohort_path) and cohorts:
        html_generator.update_cohort_tracking(
            cohort_path, cohorts, cohort_kpis_dict, cohort_configs
        )

    # ── Step 5: Process Q1 Enrollment Compliance ─────────────────────────
    logger.info("--- Processing Q1 enrollment compliance ---")

    # Determine current quarter
    quarter_start_month = ((current_month - 1) // 3) * 3 + 1
    quarter_months = [quarter_start_month, quarter_start_month + 1, quarter_start_month + 2]

    # We need credited enrollments for each month in the quarter
    monthly_credited = {}
    # Current month's data comes from the core reports
    monthly_credited[MONTH_ABBREV[current_month]] = reports.get("credited_enrollments", [])

    # For previous months in the quarter, we'd need historical data
    # These come from saved snapshots or additional API calls
    for m in quarter_months:
        abbrev = MONTH_ABBREV[m]
        if abbrev not in monthly_credited:
            # Try to load from snapshot
            snapshot = _load_month_snapshot(m, current_year, "credited_enrollments")
            if snapshot:
                monthly_credited[abbrev] = snapshot
            elif client and m < current_month:
                # Fetch with date override
                try:
                    report_id = REPORT_IDS["credited_enrollments"]
                    if report_id != "REPLACE_WITH_REPORT_ID":
                        start_date = date(current_year, m, 1)
                        if m == 12:
                            end_date = date(current_year + 1, 1, 1) - timedelta(days=1)
                        else:
                            end_date = date(current_year, m + 1, 1) - timedelta(days=1)
                        # Must include ALL saved filters (POST replaces them entirely).
                        # Report 2 saved filters: RECORDTYPE=Branch, enrollment date,
                        # and 3 conversion filters.
                        filters = [
                            {"column": "RECORDTYPE", "operator": "equals",
                             "value": "Branch"},
                            {"column": "Account.Enrollment_Date__c", "operator": "greaterOrEqual",
                             "value": start_date.isoformat()},
                            {"column": "Account.Enrollment_Date__c", "operator": "lessOrEqual",
                             "value": end_date.isoformat()},
                            {"column": "Account.Parent_EP_Converted__c", "operator": "equals",
                             "value": "True"},
                            {"column": "Account.Parent_EP_Converted_Override__c", "operator": "equals",
                             "value": "True"},
                            {"column": "Account.EP_Converted__c", "operator": "equals",
                             "value": "True"},
                        ]
                        raw = fetch_report(client, report_id, filters=filters)
                        monthly_credited[abbrev] = parse_report_rows(raw)
                except Exception as e:
                    logger.warning("Failed to fetch month %d credited enrollments: %s", m, e)
                    monthly_credited[abbrev] = []

        # If still no data, try extracting from existing HTML dashboard
        if not monthly_credited.get(abbrev) and m < current_month:
            html_rows = _extract_credited_from_html(m, current_year)
            if html_rows:
                monthly_credited[abbrev] = html_rows

    q1_data = q1_enrollment.process(monthly_credited, quarter_months, current_year)

    # Determine Q enrollment file name
    quarter_num = (quarter_start_month - 1) // 3 + 1
    q_filename = f"q{quarter_num}-enrollment.html"
    q_path = os.path.join(output_dir, q_filename)

    # Auto-create quarterly page if it doesn't exist
    if not os.path.exists(q_path):
        logger.info("Quarterly file %s doesn't exist. Creating from template.", q_filename)
        html_generator.create_quarterly_enrollment_page(quarter_num, current_year, output_dir)

    if os.path.exists(q_path):
        html_generator.update_q1_enrollment(q_path, q1_data)

    # ── Step 6: Process Field Activity ───────────────────────────────────
    logger.info("--- Processing field activity ---")
    field_data = field_activity.process(reports.get("maps_check_ins", []))

    field_path = os.path.join(output_dir, "field-activity.html")
    if os.path.exists(field_path):
        html_generator.update_field_activity(field_path, field_data)

    # ── Step 7: Update Index Page ────────────────────────────────────────
    logger.info("--- Updating index page ---")

    # Collect monthly results for all tracked months
    monthly_results = {}
    month_key = f"{MONTH_ABBREV[current_month]}-{current_year}"
    monthly_results[month_key] = monthly_data

    # Load previous months from snapshots for YTD
    for m in range(1, current_month):
        mk = f"{MONTH_ABBREV[m]}-{current_year}"
        snapshot = _load_month_snapshot_all(m, current_year)
        if snapshot:
            monthly_results[mk] = snapshot
        else:
            # Fallback: extract pre-computed data from existing HTML dashboard
            html_data = _extract_monthly_from_html(m, current_year)
            if html_data:
                monthly_results[mk] = html_data

    index_data = index_page.process(
        monthly_results=monthly_results,
        cohort_kpis=cohort_kpis_dict,
        q1_result=q1_data,
        field_result=field_data,
    )

    index_path = os.path.join(output_dir, "index.html")
    if os.path.exists(index_path):
        html_generator.update_index_page(index_path, index_data)

    logger.info("=== Dashboard update complete ===")


def _create_month_from_template(target_path: str, month: int, year: int):
    """Create a new monthly dashboard file from the previous month's template."""
    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1

    template_path = month_filepath(prev_month, prev_year)
    if not os.path.exists(template_path):
        logger.warning("No template found at %s", template_path)
        return

    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Update month references in the HTML
    old_name = MONTH_NAMES[prev_month]
    new_name = MONTH_NAMES[month]
    html = html.replace(old_name, new_name)

    old_meta = f"{old_name} {prev_year}"
    new_meta = f"{new_name} {year}"
    html = html.replace(old_meta, new_meta)

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("Created %s from template %s", target_path, template_path)


def _load_latest_snapshot() -> dict:
    """Load the most recent snapshot data."""
    snapshot_base = os.path.join(PROJECT_ROOT, "data", "snapshots")
    if not os.path.exists(snapshot_base):
        logger.warning("No snapshots directory found.")
        return {}

    dirs = sorted(os.listdir(snapshot_base), reverse=True)
    if not dirs:
        logger.warning("No snapshot directories found.")
        return {}

    latest_dir = os.path.join(snapshot_base, dirs[0])
    reports = {}
    for filename in os.listdir(latest_dir):
        if filename.endswith(".json"):
            key = filename.replace(".json", "")
            with open(os.path.join(latest_dir, filename), "r", encoding="utf-8") as f:
                reports[key] = json.load(f)
    logger.info("Loaded snapshot from %s", latest_dir)
    return reports


def _load_month_snapshot(month: int, year: int, report_key: str) -> list:
    """Load a specific report's snapshot for a given month."""
    snapshot_path = os.path.join(
        PROJECT_ROOT, "data", "snapshots",
        f"{year}-{month:02d}", f"{report_key}.json"
    )
    if os.path.exists(snapshot_path):
        with open(snapshot_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _load_month_snapshot_all(month: int, year: int) -> dict:
    """Load all snapshots for a month and run the monthly processor."""
    snapshot_dir = os.path.join(PROJECT_ROOT, "data", "snapshots", f"{year}-{month:02d}")
    if not os.path.exists(snapshot_dir):
        return None

    try:
        reports = {}
        for filename in os.listdir(snapshot_dir):
            if filename.endswith(".json"):
                key = filename.replace(".json", "")
                with open(os.path.join(snapshot_dir, filename), "r", encoding="utf-8") as f:
                    reports[key] = json.load(f)

        return monthly_dashboard.process(
            all_enrollments=reports.get("new_enrollments", []),
            credited_enrollments=reports.get("credited_enrollments", []),
            current_month_activity=reports.get("current_month_activity", []),
            last_month_activity=reports.get("last_month_activity", []),
            month=month,
            year=year,
        )
    except Exception as e:
        logger.warning("Failed to process snapshot for %d-%02d: %s", year, month, e)
        return None


def _extract_monthly_from_html(month: int, year: int) -> dict | None:
    """
    Extract pre-computed monthly dashboard data from an existing HTML file.

    Used as fallback when snapshots don't exist for historical months,
    so YTD summary and monthly cards still show correct values.
    """
    filepath = month_filepath(month, year)
    if not os.path.exists(filepath):
        logger.info("No HTML file found for %s %d", MONTH_NAMES[month], year)
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()

        # Extract total enrollments from "All Enrollments (N)"
        m = re.search(r'All Enrollments \((\d+)\)', html)
        kpi_total = int(m.group(1)) if m else 0

        # Extract OSR credited from "OSR Credited (N)"
        m = re.search(r'OSR Credited \((\d+)\)', html)
        kpi_osr = int(m.group(1)) if m else 0

        # Extract conversion rate from KPI HTML
        m = re.search(r'Conversion Rate</span><span class="kpi-value">(\d+\.?\d*)%', html)
        kpi_conversion = float(m.group(1)) if m else 0

        # Extract funded volume from KPI HTML
        m = re.search(r'Funded Volume</span><span class="kpi-value">\$([^<]+)', html)
        funded_str = m.group(1).strip() if m else "0"
        funded_amount = _parse_dollar_amount(funded_str)

        # Format funded display
        if funded_amount >= 1_000_000:
            funded_short = f"${funded_amount/1_000_000:.1f}M"
        elif funded_amount >= 1_000:
            funded_short = f"${funded_amount/1_000:.0f}K"
        else:
            funded_short = f"${int(funded_amount)}"

        # Extract repCredits from JS variable
        rep_credits = _parse_js_array(html, "repCredits")

        # Extract marketData from JS variable
        market_data = _parse_js_array(html, "marketData")

        # Create synthetic topProducers with just the funded total
        top_producers = [{"f": funded_amount}] if funded_amount > 0 else []

        logger.info(
            "Extracted from %s HTML: total=%d, osr=%d, funded=%s",
            MONTH_NAMES[month], kpi_total, kpi_osr, funded_short,
        )

        return {
            "kpi_total": kpi_total,
            "kpi_osr": kpi_osr,
            "kpi_conversion": kpi_conversion,
            "kpi_funded_display": funded_short,
            "kpi_funded_short": funded_short,
            "topProducers": top_producers,
            "repCredits": rep_credits,
            "marketData": market_data,
            "month_name": MONTH_NAMES[month],
            "year": year,
        }
    except Exception as e:
        logger.warning("Failed to extract data from %s HTML: %s", MONTH_NAMES[month], e)
        return None


def _extract_credited_from_html(month: int, year: int) -> list:
    """
    Generate synthetic credited enrollment rows from HTML dashboard data.

    Extracts repCredits from the month's HTML and generates one row per
    credited enrollment (with the OSR Enrollment Credit field set).
    Used for Q1 enrollment compliance when snapshots aren't available.
    """
    filepath = month_filepath(month, year)
    if not os.path.exists(filepath):
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()

        rep_credits = _parse_js_array(html, "repCredits")
        osr_label = COLUMN_LABELS.get("osr_credit", "OSR Enrollment Credit")

        rows = []
        for rep in rep_credits:
            name = rep.get("n", "")
            count = rep.get("v", 0)
            for _ in range(count):
                rows.append({osr_label: name})

        logger.info(
            "Generated %d synthetic credited rows from %s HTML",
            len(rows), MONTH_NAMES[month],
        )
        return rows
    except Exception as e:
        logger.warning(
            "Failed to extract credited data from %s HTML: %s",
            MONTH_NAMES[month], e,
        )
        return []


def _parse_js_array(html: str, var_name: str) -> list:
    """Parse a JS variable containing an array of simple objects from HTML."""
    pattern = rf'var {var_name}\s*=\s*(\[.*?\]);'
    m = re.search(pattern, html, re.DOTALL)
    if not m:
        return []

    js_str = m.group(1)
    # Convert JS object literal to valid JSON:
    # 1. Quote unquoted keys like {n: "foo"} → {"n": "foo"}
    json_str = re.sub(r'([{,])\s*([a-zA-Z_]\w*)\s*:', r'\1"\2":', js_str)
    # 2. Remove trailing commas before } or ]
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
    # 3. Handle JS escaped single quotes: \' → '
    json_str = json_str.replace("\\'", "'")

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse JS array '%s': %s", var_name, e)
        return []


def _parse_dollar_amount(s: str) -> float:
    """Parse a dollar amount string like '33,147' or '167K' into a float."""
    s = s.strip().replace(",", "")
    if s.upper().endswith("M"):
        return float(s[:-1]) * 1_000_000
    elif s.upper().endswith("K"):
        return float(s[:-1]) * 1_000
    else:
        try:
            return float(s)
        except ValueError:
            return 0.0


def _build_cohort_configs(current_month: int, current_year: int) -> list:
    """
    Build the cohortConfig list for all tracked cohorts.

    Each cohort corresponds to a month's enrollees. The active cohort is the
    previous month's enrollees (currently being tracked in M1). January 2026
    is always the baseline cohort.

    Returns a list of config dicts ordered: active first, then reverse chronological.
    """
    import calendar

    today = date.today()
    configs = []

    # Cohort tracking starts from Jan 2026
    start_month = 1
    start_year = 2026

    # Build configs for each enrollment month from Jan 2026 to prev_month
    for enrollment_month in range(start_month, current_month):
        enrollment_year = current_year
        m0_abbrev = MONTH_ABBREV[enrollment_month]

        # M1 = enrollment_month + 1
        m1_month = enrollment_month + 1
        m1_year = enrollment_year
        if m1_month > 12:
            m1_month = 1
            m1_year += 1

        # M2 = enrollment_month + 2
        m2_month = enrollment_month + 2
        m2_year = enrollment_year
        if m2_month > 12:
            m2_month -= 12
            m2_year += 1

        # Determine M1 status
        m1_complete = (m1_year < today.year or
                       (m1_year == today.year and m1_month < today.month))
        m1_in_progress = (m1_year == today.year and m1_month == today.month)

        # Determine cohort type
        if enrollment_month == start_month and enrollment_year == start_year:
            cohort_type = "baseline"
        elif enrollment_month == current_month - 1:
            cohort_type = "active"
        else:
            cohort_type = "completed"

        # Month keys and labels for the merchant table
        month_keys = [m0_abbrev, MONTH_ABBREV[m1_month]]
        m0_label = MONTH_NAMES[enrollment_month][:3]
        m1_label = MONTH_NAMES[m1_month][:3]
        month_labels = [f"{m0_label} $", f"{m1_label} $"]

        # Add M2 column if M1 is complete (true-up tracking available)
        has_m2 = m1_complete
        if has_m2:
            m2_abbrev = MONTH_ABBREV[m2_month]
            month_keys.append(m2_abbrev)
            m2_label = MONTH_NAMES[m2_month][:3]
            month_labels.append(f"{m2_label} $")

        # Build deadline info
        if m1_in_progress:
            _, days_in_month = calendar.monthrange(today.year, today.month)
            days_remaining = days_in_month - today.day
            deadline = f"{MONTH_NAMES[m1_month]} (M1 in progress)"
            deadline_sub = f"{days_remaining} days remaining"
        elif m1_complete:
            deadline = f"{MONTH_NAMES[m1_month]} (M1 complete)"
            deadline_sub = "M1 closed, M2 true-up available"
        else:
            deadline = f"{MONTH_NAMES[m1_month]} (upcoming)"
            deadline_sub = ""

        # Note text (HTML)
        if cohort_type == "active":
            note = (f'<div class="note"><b>Active cohort</b> &mdash; '
                    f'{MONTH_NAMES[enrollment_month]} enrollees must produce $15K by end of '
                    f'{MONTH_NAMES[m1_month]} (M0+M1). Miss? $30K by end of '
                    f'{MONTH_NAMES[m2_month]} (M2 true-up).</div>')
        elif cohort_type == "baseline":
            note = (f'<div class="note"><b>Baseline cohort (pre-commission structure)</b> '
                    f'&mdash; {MONTH_NAMES[enrollment_month]} cohort tracked retroactively. '
                    f'Month 2 true-up: $30K by end of {MONTH_NAMES[m2_month]}.</div>')
        else:
            note = (f'<div class="note"><b>Completed cohort</b> &mdash; '
                    f'{MONTH_NAMES[enrollment_month]} enrollees, M1 deadline was end of '
                    f'{MONTH_NAMES[m1_month]}.</div>')

        label = f"{MONTH_NAMES[enrollment_month][:3]} \u2192 {MONTH_NAMES[m1_month][:3]}"

        configs.append({
            "id": m0_abbrev,
            "label": label,
            "varName": f"{m0_abbrev}Cohort",
            "type": cohort_type,
            "note": note,
            "monthKeys": month_keys,
            "monthLabels": month_labels,
            "hasM2": has_m2,
            "deadline": deadline,
            "deadlineSub": deadline_sub,
        })

    # Sort: active first, then reverse chronological
    type_order = {"active": 0, "completed": 1, "baseline": 2}
    configs.sort(key=lambda c: (type_order.get(c["type"], 1),
                                 -_month_num_from_id(c["id"])))

    logger.info("Built %d cohort configs: %s",
                len(configs),
                ", ".join(f'{c["label"]} ({c["type"]})' for c in configs))

    return configs


def _month_num_from_id(month_id: str) -> int:
    """Convert month abbreviation to month number for sorting."""
    month_map = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                 "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    return month_map.get(month_id, 0)


if __name__ == "__main__":
    main()
