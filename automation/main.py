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

    # Normalize enrollment rows so all processors see display values
    # instead of raw Salesforce IDs (SUMMARY format stores IDs in main keys,
    # display labels in _label_ prefixed keys).
    for report_key in ("credited_enrollments", "new_enrollments"):
        if reports.get(report_key):
            reports[report_key] = _normalize_enrollment_rows(
                reports[report_key]
            )

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

    # 1. Get activity data FIRST — we need it to build enrollment list from HTML fallback
    #    Report 4 (last_month_activity) already contains activity for merchants
    #    enrolled LAST MONTH (= our active cohort).
    active_cohort_activity = {}
    last_month_activity = reports.get("last_month_activity", [])
    if last_month_activity:
        active_cohort_activity = _normalize_matrix_to_monthly(last_month_activity)
        logger.info("Normalized matrix activity into %d months: %s",
                     len(active_cohort_activity),
                     {k: len(v) for k, v in active_cohort_activity.items()})

    # If no matrix data, try dedicated cohort fetch
    if not active_cohort_activity and client:
        try:
            cohort_matrix = fetch_cohort_activity(
                client, prev_month, prev_year, current_month, current_year
            )
            active_cohort_activity = _normalize_matrix_to_monthly(cohort_matrix)
        except Exception as e:
            logger.warning("Failed to fetch cohort activity: %s", e)

    # 2. Get active cohort ENROLLMENT LIST (prev month's credited enrollments)
    #    NOT current month's reports["credited_enrollments"] — that's this month's data!
    active_cohort_enrollments = _load_month_snapshot(prev_month, prev_year, "credited_enrollments")
    if active_cohort_enrollments:
        logger.info("Loaded %d active cohort enrollments from %s %d snapshot",
                     len(active_cohort_enrollments), MONTH_ABBREV[prev_month], prev_year)
        active_cohort_enrollments = _normalize_enrollment_rows(active_cohort_enrollments)
    elif client:
        active_cohort_enrollments = _fetch_credited_for_month(client, prev_month, prev_year)
        if active_cohort_enrollments:
            active_cohort_enrollments = _normalize_enrollment_rows(active_cohort_enrollments)
    if not active_cohort_enrollments:
        # HTML fallback: build enrollment list from activity data (has Branch IDs)
        # combined with repMerchants (has OSR → merchant name mapping)
        active_cohort_enrollments = _build_enrollment_from_activity_and_html(
            prev_month, prev_year, active_cohort_activity
        )

    # 3. Build active cohort
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

    # Update cohort-tracking.html (always update configs/tabs, even if no new data)
    cohort_path = os.path.join(output_dir, "cohort-tracking.html")
    if os.path.exists(cohort_path) and (cohorts or cohort_configs):
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
                monthly_credited[abbrev] = _normalize_enrollment_rows(snapshot)
            elif client and m < current_month:
                # Fetch with date override + boolean filter for OR logic
                rows = _fetch_credited_for_month(client, m, current_year)
                if rows:
                    monthly_credited[abbrev] = _normalize_enrollment_rows(rows)

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


def _normalize_enrollment_rows(rows: list) -> list:
    """
    Normalize SUMMARY-format enrollment rows to use display values.

    The SUMMARY report parser stores raw Salesforce API values in the main keys
    and display labels in _label_ prefixed keys:
        {"Account Name": "001TO000...", "_label_Account Name": "Merchant Name",
         "OSR Enrollment Credit": "-", "_label_OSR": "Rep Name"}

    This normalizer replaces raw values with display values for fields where
    the raw value is a Salesforce ID or null placeholder ("-").
    """
    normalized = []
    osr_label = COLUMN_LABELS.get("osr_credit", "OSR Enrollment Credit")
    merchant_label = COLUMN_LABELS.get("merchant_name", "Account Name")

    for row in rows:
        new_row = dict(row)

        # Fix OSR name: "OSR Enrollment Credit" often = "-" in SUMMARY format.
        # The actual name is in "_label_OSR" (authoritative) or "Referral/Promo Code" (free-text).
        # IMPORTANT: Check _label_OSR first — "Referral/Promo Code" is a free-text field
        # that may contain abbreviations like "Stephanie" or "mm" instead of full names.
        osr_val = row.get(osr_label, "")
        if not osr_val or osr_val == "-":
            for alt in ("_label_OSR", f"_label_{osr_label}",
                        "Referral/Promo Code"):
                alt_val = row.get(alt)
                if alt_val and alt_val != "-":
                    new_row[osr_label] = alt_val
                    break

        # Fix merchant name: raw value is a Salesforce Account ID.
        # Display name lives in "_label_Account Name".
        name_val = row.get(merchant_label, "")
        label_name = row.get(f"_label_{merchant_label}", "")
        if label_name and label_name != "-" and label_name != name_val:
            new_row[merchant_label] = label_name

        # Fix ISR name: raw value is a Salesforce User ID (e.g., "005TO000...").
        # Display name lives in "_label_ISR".
        isr_label = COLUMN_LABELS.get("isr_assignment", "ISR")
        isr_val = row.get(isr_label, "")
        label_isr = row.get(f"_label_{isr_label}", "")
        if label_isr and label_isr != "-" and label_isr != isr_val:
            new_row[isr_label] = label_isr

        normalized.append(new_row)

    return normalized


def _fetch_credited_for_month(client, month: int, year: int) -> list:
    """
    Fetch Report 2 (credited enrollments) for a specific past month via API.

    Uses POST with date filter overrides and a boolean filter expression
    to correctly handle the OR logic for conversion filters (any one of
    Parent_EP_Converted, Parent_EP_Converted_Override, or EP_Converted
    being True means the merchant is converted).
    """
    report_id = REPORT_IDS["credited_enrollments"]
    if report_id == "REPLACE_WITH_REPORT_ID":
        return []

    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)

    # Report 2 saved filters use OR logic for 3 conversion flags:
    # (Parent_EP_Converted OR Parent_EP_Converted_Override OR EP_Converted)
    # POST replaces ALL saved filters, so we must replicate the OR via
    # reportBooleanFilter.
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

    try:
        raw = fetch_report(
            client, report_id, filters=filters,
            boolean_filter="1 AND 2 AND 3 AND (4 OR 5 OR 6)"
        )
        rows = parse_report_rows(raw)
        if rows:
            logger.info("Fetched %d credited enrollments for %s %d via API",
                         len(rows), MONTH_ABBREV[month], year)
            return rows
    except Exception as e:
        logger.warning("Failed to fetch credited enrollments for %s %d: %s",
                        MONTH_ABBREV[month], year, e)

    return []


def _normalize_matrix_to_monthly(matrix_rows: list) -> dict:
    """
    Convert matrix report rows (date-prefixed columns) into per-month flat rows.

    Matrix reports (Report 4) return rows like:
        {"Account Name": "X", "Branch ID": "123",
         "2/1/2026_Sum of Funded Dollars": 5000, "3/1/2026_Sum of Funded Dollars": 3000}

    This function splits each row into per-month entries with standard column names:
        {"feb": [{"Account Name": "X", "Branch ID": "123", "# Funded Dollars": 5000}],
         "mar": [{"Account Name": "X", "Branch ID": "123", "# Funded Dollars": 3000}]}

    The column renaming (e.g., "Sum of Funded Dollars" → "# Funded Dollars")
    ensures compatibility with cohort_tracking.process_cohort() which uses
    COLUMN_LABELS for lookups.
    """
    from collections import defaultdict

    # Map matrix aggregate labels to standard COLUMN_LABELS values
    agg_map = {
        "Sum of Funded Dollars": COLUMN_LABELS["funded_dollars"],
        "Sum of Funded Applications Total": COLUMN_LABELS["funded_apps"],
        "Sum of Applications": COLUMN_LABELS["total_apps"],
        "Sum of Funded Average": COLUMN_LABELS["funded_avg"],
    }

    monthly = defaultdict(list)

    for row in matrix_rows:
        month_data = defaultdict(dict)  # month_abbrev → {standard_col: value}
        base_data = {}  # non-date columns (Account Name, Branch ID)

        for col, val in row.items():
            # Match date prefix: "2/1/2026_Sum of Funded Dollars"
            m = re.match(r'^(\d{1,2})/\d{1,2}/(\d{4})_(.+)$', col)
            if not m:
                # Try ISO format: "2026-02-01_..."
                m = re.match(r'^(\d{4})-(\d{2})-\d{2}_(.+)$', col)
                if m:
                    month_num = int(m.group(2))
                    base_col = m.group(3)
                else:
                    base_data[col] = val
                    continue
            else:
                month_num = int(m.group(1))
                base_col = m.group(3)

            abbrev = MONTH_ABBREV.get(month_num, f"m{month_num}")
            mapped_col = agg_map.get(base_col, base_col)
            month_data[abbrev][mapped_col] = val

        # Create a flat row for each month that has data
        for month_abbrev, cols in month_data.items():
            flat_row = dict(base_data)
            flat_row.update(cols)
            monthly[month_abbrev].append(flat_row)

    return dict(monthly)


def _build_enrollment_from_activity_and_html(month: int, year: int,
                                               activity: dict) -> list:
    """
    Build a credited enrollment list by combining two data sources:
    1. Matrix activity data (Report 4) — has Branch IDs and Account Names
    2. repMerchants from HTML dashboard — has OSR → merchant name mapping

    This is used when no snapshot or API data is available for the enrollment
    month.  The activity data provides the definitive list of merchants with
    their Branch IDs, and the HTML repMerchants provides the OSR attribution.
    """
    osr_label = COLUMN_LABELS.get("osr_credit", "OSR Enrollment Credit")
    merchant_label = COLUMN_LABELS.get("merchant_name", "Account Name")
    branch_label = COLUMN_LABELS.get("branch_id", "Branch ID")

    # Step 1: Build OSR lookup from repMerchants in the monthly HTML
    osr_by_merchant_name = _build_osr_lookup_from_html(month, year)

    # Step 2: Build enrollment rows from activity data (has Branch IDs)
    # Collect unique merchants from all months of activity
    seen_branches = set()
    rows = []

    for month_key, month_rows in activity.items():
        for row in month_rows:
            branch = str(row.get(branch_label, ""))
            if not branch or branch in seen_branches:
                continue
            seen_branches.add(branch)

            name = row.get(merchant_label, "Unknown")
            osr = osr_by_merchant_name.get(name, "")

            if osr:
                rows.append({
                    osr_label: osr,
                    merchant_label: name,
                    branch_label: branch,
                })

    if rows:
        logger.info("Built %d enrollment rows from activity data + HTML OSR lookup for %s %d",
                     len(rows), MONTH_NAMES[month], year)
    else:
        logger.warning("Could not build enrollment list for %s %d — "
                        "falling back to simple HTML extraction",
                        MONTH_NAMES[month], year)
        rows = _extract_credited_from_html(month, year)

    return rows


def _build_osr_lookup_from_html(month: int, year: int) -> dict:
    """
    Build a merchant_name → OSR name lookup from repMerchants in HTML.

    Returns dict mapping merchant display name to OSR name.
    """
    filepath = month_filepath(month, year)
    if not os.path.exists(filepath):
        return {}

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()

        rep_merchants = _parse_js_object(html, "repMerchants")
        if not rep_merchants:
            return {}

        lookup = {}
        for osr_name, merchants in rep_merchants.items():
            for m in merchants:
                name = m.get("n", "")
                if name:
                    lookup[name] = osr_name

        logger.info("Built OSR lookup with %d merchants from %s HTML",
                     len(lookup), MONTH_NAMES[month])
        return lookup

    except Exception as e:
        logger.warning("Failed to build OSR lookup from %s HTML: %s",
                        MONTH_NAMES[month], e)
        return {}


def _extract_credited_with_merchants(month: int, year: int) -> list:
    """
    Extract credited enrollment rows with branch IDs and OSR mapping from HTML.

    Parses the repMerchants JS object from the monthly dashboard to get
    per-rep merchant lists with branch IDs — more detailed than
    _extract_credited_from_html() which only produces rep name + count.
    """
    filepath = month_filepath(month, year)
    if not os.path.exists(filepath):
        return _extract_credited_from_html(month, year)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()

        rep_merchants = _parse_js_object(html, "repMerchants")
        if not rep_merchants:
            logger.info("No repMerchants found in %s HTML, falling back to simple extraction",
                         MONTH_NAMES[month])
            return _extract_credited_from_html(month, year)

        osr_label = COLUMN_LABELS.get("osr_credit", "OSR Enrollment Credit")
        merchant_label = COLUMN_LABELS.get("merchant_name", "Account Name")
        branch_label = COLUMN_LABELS.get("branch_id", "Branch ID")

        rows = []
        for rep_name, merchants in rep_merchants.items():
            for m in merchants:
                rows.append({
                    osr_label: rep_name,
                    merchant_label: m.get("n", "Unknown"),
                    branch_label: str(m.get("b", "")),
                })

        if rows:
            logger.info("Extracted %d credited enrollments with merchants from %s HTML",
                         len(rows), MONTH_NAMES[month])
            return rows
        else:
            return _extract_credited_from_html(month, year)

    except Exception as e:
        logger.warning("Failed to extract credited merchants from %s HTML: %s",
                        MONTH_NAMES[month], e)
        return _extract_credited_from_html(month, year)


def _parse_js_object(html: str, var_name: str) -> dict:
    """
    Parse a JS variable containing an object from HTML.

    Handles repMerchants-style objects:
        var repMerchants={"Rep Name":[{n:"Merchant",b:12345}, ...], ...};
    """
    pattern = rf'var {var_name}=(\{{.*?\}});'
    m = re.search(pattern, html, re.DOTALL)
    if not m:
        return {}

    js_str = m.group(1)
    # Convert JS to JSON:
    # 1. Quote unquoted keys like {n: "foo"} → {"n": "foo"}
    json_str = re.sub(r'([{,])\s*([a-zA-Z_]\w*)\s*:', r'\1"\2":', js_str)
    # 2. Remove trailing commas
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
    # 3. Handle escaped single quotes
    json_str = json_str.replace("\\'", "'")

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse JS object '%s': %s", var_name, e)
        return {}


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
