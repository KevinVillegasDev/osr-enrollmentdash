"""
Salesforce Analytics REST API report fetcher.

Fetches the 5 core reports + cohort-specific variants using POST with optional
filter overrides. Includes retry logic with exponential backoff.

Handles both TABULAR reports (Reports 1, 2, 3, 5) and MATRIX/SUMMARY reports
(Report 4 — grouped by Account Name + Branch ID, column-grouped by First Date of Month).
"""

import logging
import time
from datetime import date, timedelta

from .config import SF_API_VERSION, REPORT_IDS, MONTH_ABBREV

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds, doubles each retry


def _report_url(report_id: str) -> str:
    """Build the Analytics REST API path for a report."""
    return f"/services/data/{SF_API_VERSION}/analytics/reports/{report_id}"


def fetch_report(client, report_id: str, filters: list = None) -> dict:
    """
    Execute a Salesforce report synchronously and return the full JSON response.

    Args:
        client: Authenticated SalesforceClient instance
        report_id: 18-character Salesforce Report ID
        filters: Optional list of reportFilter dicts to override the saved filters

    Returns:
        Full report response JSON with factMap, reportMetadata, reportExtendedMetadata

    Raises:
        RuntimeError: If all retries are exhausted
    """
    path = _report_url(report_id)
    use_post = filters is not None
    body = None
    if filters:
        body = {"reportMetadata": {"reportFilters": filters}}

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("Fetching report %s (attempt %d/%d, method=%s)",
                        report_id, attempt, MAX_RETRIES, "POST" if use_post else "GET")
            if use_post:
                result = client.post(path, body=body)
            else:
                result = client.get(path)

            # Check if all data was returned
            all_data = result.get("allData", True)
            if not all_data:
                logger.warning(
                    "Report %s returned partial data (>2000 rows). "
                    "Some rows may be missing.", report_id
                )

            # Log format, filters, and column info
            report_format = result.get("reportMetadata", {}).get("reportFormat", "UNKNOWN")
            report_filters = result.get("reportMetadata", {}).get("reportFilters", [])
            detail_cols = result.get("reportMetadata", {}).get("detailColumns", [])
            group_cols_down = result.get("reportMetadata", {}).get("groupingsDown", [])
            group_cols_across = result.get("reportMetadata", {}).get("groupingsAcross", [])
            logger.info("Report %s: format=%s, filters=%s", report_id, report_format, report_filters)
            logger.info("Report %s: detailColumns=%s", report_id, detail_cols)
            logger.info("Report %s: groupingsDown=%s, groupingsAcross=%s",
                        report_id, group_cols_down, group_cols_across)
            return result

        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF ** attempt
                logger.warning(
                    "Report %s fetch failed (attempt %d): %s. Retrying in %ds...",
                    report_id, attempt, str(e), wait
                )
                time.sleep(wait)
            else:
                logger.error("Report %s fetch failed after %d attempts: %s",
                             report_id, MAX_RETRIES, str(e))

    raise RuntimeError(f"Failed to fetch report {report_id} after {MAX_RETRIES} attempts: {last_error}")


def parse_report_rows(report_json: dict) -> list[dict]:
    """
    Parse a Salesforce report response into a list of row dicts.
    Automatically detects TABULAR vs SUMMARY/MATRIX format.

    Each row dict maps column label -> cell value.

    Args:
        report_json: Full report JSON response from fetch_report()

    Returns:
        List of dicts, one per row, keyed by column label
    """
    metadata = report_json.get("reportMetadata", {})
    report_format = metadata.get("reportFormat", "TABULAR")

    if report_format == "MATRIX":
        return _parse_matrix_report(report_json)
    elif report_format == "SUMMARY":
        return _parse_summary_report(report_json)
    else:
        return _parse_tabular_report(report_json)


def _parse_tabular_report(report_json: dict) -> list[dict]:
    """Parse a TABULAR Salesforce report (Reports 1, 2, 3, 5)."""
    metadata = report_json.get("reportMetadata", {})
    extended = report_json.get("reportExtendedMetadata", {})
    fact_map = report_json.get("factMap", {})

    detail_columns = metadata.get("detailColumns", [])

    col_info = extended.get("detailColumnInfo", {})
    label_map = {}
    for api_name in detail_columns:
        info = col_info.get(api_name, {})
        label_map[api_name] = info.get("label", api_name)

    rows = []
    for key in sorted(fact_map.keys()):
        section = fact_map[key]
        for row in section.get("rows", []):
            cells = row.get("dataCells", [])
            row_dict = {}
            for i, api_name in enumerate(detail_columns):
                if i < len(cells):
                    cell = cells[i]
                    row_dict[label_map[api_name]] = cell.get("value", cell.get("label", ""))
                    row_dict[f"_label_{label_map[api_name]}"] = cell.get("label", "")
            rows.append(row_dict)

    logger.info("Parsed %d rows from tabular report", len(rows))
    return rows


def _parse_summary_report(report_json: dict) -> list[dict]:
    """
    Parse a SUMMARY Salesforce report.

    Summary reports group rows by one or more fields. The factMap keys
    are like "0!T" (group 0 total), "1!T" (group 1 total), etc.
    Detail rows are under keys without "T" suffix.
    """
    metadata = report_json.get("reportMetadata", {})
    extended = report_json.get("reportExtendedMetadata", {})
    fact_map = report_json.get("factMap", {})
    groupings = report_json.get("groupingsDown", {}).get("groupings", [])

    detail_columns = metadata.get("detailColumns", [])
    raw_group_columns = metadata.get("groupingsDown", [])

    # groupingsDown entries may be dicts with 'name' key or plain strings
    group_column_names = []
    for g in raw_group_columns:
        if isinstance(g, dict):
            group_column_names.append(g.get("name", str(g)))
        else:
            group_column_names.append(str(g))

    col_info = extended.get("detailColumnInfo", {})
    grouping_info = extended.get("groupingColumnInfo", {})
    label_map = {}
    for api_name in detail_columns:
        info = col_info.get(api_name, {})
        label_map[api_name] = info.get("label", api_name)

    # Build grouping column label lookup (API name → display label)
    group_label_map = {}
    for api_name in group_column_names:
        # Check groupingColumnInfo first, then detailColumnInfo
        info = grouping_info.get(api_name, col_info.get(api_name, {}))
        group_label_map[api_name] = info.get("label", api_name)

    # Build grouping value lookup (factMap key → list of grouping values)
    group_labels = {}
    _extract_grouping_labels(groupings, group_labels, [])

    rows = []
    for key in sorted(fact_map.keys()):
        # Skip grand total and subtotal rows (keys ending in "T")
        if key.endswith("!T") or key == "T!T":
            continue

        section = fact_map[key]
        for row in section.get("rows", []):
            cells = row.get("dataCells", [])
            row_dict = {}

            # Add grouping fields
            if key in group_labels:
                for group_name, group_val in zip(group_column_names, group_labels[key]):
                    g_label = group_label_map.get(group_name, group_name)
                    row_dict[g_label] = group_val

            # Add detail columns
            for i, api_name in enumerate(detail_columns):
                if i < len(cells):
                    cell = cells[i]
                    row_dict[label_map[api_name]] = cell.get("value", cell.get("label", ""))
                    row_dict[f"_label_{label_map[api_name]}"] = cell.get("label", "")
            rows.append(row_dict)

    logger.info("Parsed %d rows from summary report", len(rows))
    return rows


def _parse_matrix_report(report_json: dict) -> list[dict]:
    """
    Parse a MATRIX Salesforce report (Report 4 — activity report).

    Matrix reports have row groupings AND column groupings.
    Report 4 structure:
    - Row groups: Account Name, Branch ID
    - Column group: First Date of Month (creates per-month columns)
    - Aggregates: # Funded Dollars, # Funded Applications Total, # Applications, etc.

    Returns a flat list of dicts, one per merchant, with per-month funding data:
    {
        "Account Name": "Merchant Name",
        "Branch ID": "12345",
        "2026-02-01_# Funded Dollars": 5000.00,
        "2026-02-01_# Applications": 10,
        "2026-03-01_# Funded Dollars": 3000.00,
        ...
    }
    """
    metadata = report_json.get("reportMetadata", {})
    extended = report_json.get("reportExtendedMetadata", {})
    fact_map = report_json.get("factMap", {})

    # Row groupings (Account Name, Branch ID)
    row_groupings = report_json.get("groupingsDown", {}).get("groupings", [])

    # Column groupings (First Date of Month)
    col_groupings = report_json.get("groupingsAcross", {}).get("groupings", [])

    # Aggregate column info
    agg_info = extended.get("aggregateColumnInfo", {})
    agg_columns = metadata.get("aggregates", [])

    # Build column group labels: index -> date label
    col_labels = {}
    for i, grp in enumerate(col_groupings):
        col_labels[str(i)] = grp.get("label", grp.get("value", f"col_{i}"))

    # Build row group hierarchy: row index -> {Account Name, Branch ID}
    row_merchants = []
    _extract_row_groups(row_groupings, row_merchants, {})

    logger.info("Matrix report: %d row groups, %d column groups, %d aggregates",
                len(row_merchants), len(col_labels), len(agg_columns))

    # Build aggregate label map
    agg_labels = []
    for agg_api in agg_columns:
        info = agg_info.get(agg_api, {})
        agg_labels.append(info.get("label", agg_api))

    # Parse factMap
    # Keys are like "0_0!0_0" (row0_subrow0!col0_subcol0)
    # or "0!0" for single-level groupings
    # The "!" separates row key from column key
    rows_out = {}

    for key, section in fact_map.items():
        if "!" not in key:
            continue

        row_key, col_key = key.split("!", 1)

        # Skip grand totals (T)
        if row_key == "T" or col_key == "T":
            continue

        # Get the row index (first number before any underscore)
        row_parts = row_key.split("_")
        row_idx = row_parts[0]

        # Get column index
        col_parts = col_key.split("_")
        col_idx = col_parts[0]

        # Get column label (month date)
        month_label = col_labels.get(col_idx, f"month_{col_idx}")

        # Get aggregates for this cell
        aggregates = section.get("aggregates", [])

        # Initialize row if needed
        if row_idx not in rows_out:
            # Find merchant info from row groupings
            idx = int(row_idx) if row_idx.isdigit() else 0
            if idx < len(row_merchants):
                rows_out[row_idx] = dict(row_merchants[idx])
            else:
                rows_out[row_idx] = {}

        # Add per-month aggregate values
        for i, agg_val in enumerate(aggregates):
            label = agg_labels[i] if i < len(agg_labels) else f"agg_{i}"
            val = agg_val.get("value", 0)
            rows_out[row_idx][f"{month_label}_{label}"] = val

    result = list(rows_out.values())
    logger.info("Parsed %d merchants from matrix report", len(result))
    return result


def _extract_row_groups(groupings: list, result: list, current: dict):
    """Recursively extract row group labels from nested groupings."""
    for grp in groupings:
        entry = dict(current)
        label = grp.get("label", grp.get("value", ""))
        key = grp.get("key", "")

        # Determine the group field name from the level
        # Level 0 = Account Name, Level 1 = Branch ID (for Report 4)
        sub_groupings = grp.get("groupings", [])

        if sub_groupings:
            # This is a parent group (Account Name)
            entry["Account Name"] = label
            _extract_row_groups(sub_groupings, result, entry)
        else:
            # This is a leaf group (Branch ID)
            entry["Branch ID"] = label
            result.append(entry)


def _extract_grouping_labels(groupings: list, label_map: dict, path: list):
    """Recursively build a map of factMap keys to grouping label lists."""
    for i, grp in enumerate(groupings):
        current_path = path + [str(i)]
        key = "_".join(current_path)
        label = grp.get("label", grp.get("value", ""))

        sub = grp.get("groupings", [])
        if sub:
            _extract_grouping_labels(sub, label_map, current_path)
        else:
            label_map[key] = [label]


def fetch_all_reports(client) -> dict:
    """
    Fetch all 5 core Salesforce reports.

    Returns:
        Dict with keys: new_enrollments, credited_enrollments,
        current_month_activity, last_month_activity, maps_check_ins.
        Each value is the parsed list of row dicts.
    """
    results = {}

    for report_key, report_id in REPORT_IDS.items():
        if report_id == "REPLACE_WITH_REPORT_ID":
            logger.warning("Report '%s' has placeholder ID. Skipping.", report_key)
            results[report_key] = []
            continue

        raw = fetch_report(client, report_id)
        results[report_key] = parse_report_rows(raw)
        logger.info("Parsed %d entries for '%s'", len(results[report_key]), report_key)

    return results


def fetch_cohort_activity(client, enrollment_month: int, enrollment_year: int,
                          activity_month: int, activity_year: int) -> list[dict]:
    """
    Fetch funding activity for a specific enrollment cohort in a specific month.

    Uses the last_month_activity report template with date filter overrides
    to pull activity for merchants enrolled in a specific month.

    Args:
        client: Authenticated SalesforceClient
        enrollment_month: Month the merchants were enrolled (1-12)
        enrollment_year: Year the merchants were enrolled
        activity_month: Month of activity data to pull (1-12)
        activity_year: Year of activity data to pull

    Returns:
        List of parsed row dicts (matrix format with per-month columns)
    """
    report_id = REPORT_IDS["last_month_activity"]
    if report_id == "REPLACE_WITH_REPORT_ID":
        logger.warning("last_month_activity report has placeholder ID. Skipping cohort fetch.")
        return []

    # Build date range for enrollment month
    enroll_start = date(enrollment_year, enrollment_month, 1)
    if enrollment_month == 12:
        enroll_end = date(enrollment_year + 1, 1, 1) - timedelta(days=1)
    else:
        enroll_end = date(enrollment_year, enrollment_month + 1, 1) - timedelta(days=1)

    # Must include ALL saved filters (POST replaces them entirely).
    # Report 4 saved filters: RECORDTYPE=Branch, Account.Enrollment_Date__c=LAST MONTH
    # We keep RECORDTYPE and override the enrollment date range.
    filters = [
        {
            "column": "RECORDTYPE",
            "operator": "equals",
            "value": "Branch",
        },
        {
            "column": "Account.Enrollment_Date__c",
            "operator": "greaterOrEqual",
            "value": enroll_start.isoformat(),
        },
        {
            "column": "Account.Enrollment_Date__c",
            "operator": "lessOrEqual",
            "value": enroll_end.isoformat(),
        },
    ]

    logger.info(
        "Fetching cohort activity: enrolled %s %d, activity for %s %d",
        MONTH_ABBREV[enrollment_month].title(), enrollment_year,
        MONTH_ABBREV[activity_month].title(), activity_year,
    )

    raw = fetch_report(client, report_id, filters=filters)
    return parse_report_rows(raw)
