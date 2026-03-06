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


def fetch_report(client, report_id: str, filters: list = None,
                 boolean_filter: str = None) -> dict:
    """
    Execute a Salesforce report synchronously and return the full JSON response.

    Args:
        client: Authenticated SalesforceClient instance
        report_id: 18-character Salesforce Report ID
        filters: Optional list of reportFilter dicts to override the saved filters
        boolean_filter: Optional boolean filter expression for AND/OR logic,
                       e.g. "1 AND 2 AND 3 AND (4 OR 5 OR 6)".
                       Only used when filters are also provided.

    Returns:
        Full report response JSON with factMap, reportMetadata, reportExtendedMetadata

    Raises:
        RuntimeError: If all retries are exhausted
    """
    path = _report_url(report_id)
    # includeDetails=true ensures SUMMARY reports return detail rows
    # (not just group subtotals).  Without this, the factMap only
    # contains keys like "0!T" and the parser returns 0 rows.
    query_params = {"includeDetails": "true"}
    use_post = filters is not None
    body = None
    if filters:
        metadata = {"reportFilters": filters}
        if boolean_filter:
            metadata["reportBooleanFilter"] = boolean_filter
        body = {"reportMetadata": metadata}

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("Fetching report %s (attempt %d/%d, method=%s, params=%s)",
                        report_id, attempt, MAX_RETRIES, "POST" if use_post else "GET", query_params)
            if use_post:
                result = client.post(path, body=body, params=query_params)
            else:
                result = client.get(path, params=query_params)

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

    has_detail_rows = metadata.get("hasDetailRows", False)
    logger.info("Summary report factMap keys: %s (hasDetailRows=%s, groupings=%d)",
                sorted(fact_map.keys()), has_detail_rows, len(groupings))

    rows = []
    for key in sorted(fact_map.keys()):
        # Skip grand total
        if key == "T!T":
            continue

        section = fact_map[key]
        section_rows = section.get("rows", [])

        # For summary reports, detail rows live inside the group subtotal
        # sections (keys like "0!T", "1!T").  Only skip subtotal keys if
        # there are also non-subtotal detail keys in the factMap.
        is_subtotal = key.endswith("!T")
        if is_subtotal and not section_rows:
            continue

        # Determine the grouping index for this key
        # "0!T" → group index "0", "0_0" → group index "0"
        group_idx = key.split("!")[0].split("_")[0] if "!" in key or "_" in key else key

        for row in section_rows:
            cells = row.get("dataCells", [])
            row_dict = {}

            # Add grouping fields — look up by group index
            if group_idx in group_labels:
                for group_name, group_val in zip(group_column_names, group_labels[group_idx]):
                    g_label = group_label_map.get(group_name, group_name)
                    row_dict[g_label] = group_val
            elif key in group_labels:
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

    # Build row group hierarchy: compound key -> {Account Name, Branch ID}
    # key_map maps factMap compound keys (e.g., "0_0", "1_0") to flat indices
    # in row_merchants, so we correctly handle parents with multiple children.
    row_merchants = []
    row_key_map = {}
    _extract_row_groups(row_groupings, row_merchants, {}, row_key_map)

    logger.info("Matrix report: %d row groups (leaves), %d compound keys, %d column groups, %d aggregates",
                len(row_merchants), len(row_key_map), len(col_labels), len(agg_columns))

    # Build aggregate label map
    agg_labels = []
    for agg_api in agg_columns:
        info = agg_info.get(agg_api, {})
        agg_labels.append(info.get("label", agg_api))

    # Parse factMap
    # Keys are like "0_0!0_0" (parent0_child0!col0_subcol0)
    # or "0!0" for single-level groupings
    # The "!" separates row key from column key
    # IMPORTANT: Use the FULL compound row key (e.g., "0_0", "0_1", "1_0")
    # to distinguish each leaf node. Using only the parent index would collapse
    # all children under one parent and shift all subsequent merchants.
    rows_out = {}

    for key, section in fact_map.items():
        if "!" not in key:
            continue

        row_key, col_key = key.split("!", 1)

        # Skip grand totals (T)
        if row_key == "T" or col_key == "T":
            continue

        # Get column index (first number — columns are single-level for our reports)
        col_parts = col_key.split("_")
        col_idx = col_parts[0]

        # Get column label (month date)
        month_label = col_labels.get(col_idx, f"month_{col_idx}")

        # Get aggregates for this cell
        aggregates = section.get("aggregates", [])

        # Initialize row if needed — use FULL compound row_key.
        # Only process row keys that match a leaf node in the compound key map.
        # The factMap also contains parent-level summary keys (e.g., "7!0" for
        # all children under parent 7), which we skip to avoid duplicates.
        if row_key not in rows_out:
            flat_idx = row_key_map.get(row_key, -1)
            if 0 <= flat_idx < len(row_merchants):
                rows_out[row_key] = dict(row_merchants[flat_idx])
            else:
                # Skip parent-level summary keys — they aggregate child data
                # which we already capture at the leaf level
                continue

        # Add per-month aggregate values
        for i, agg_val in enumerate(aggregates):
            label = agg_labels[i] if i < len(agg_labels) else f"agg_{i}"
            val = agg_val.get("value", 0)
            rows_out[row_key][f"{month_label}_{label}"] = val

    result = list(rows_out.values())
    logger.info("Parsed %d merchants from matrix report", len(result))
    return result


def _extract_row_groups(groupings: list, result: list, current: dict,
                        key_map: dict = None, path: list = None):
    """
    Recursively extract row group labels from nested groupings.

    Also builds a compound-key → flat-index mapping so the matrix parser
    can correctly look up merchants by their factMap row key.

    Args:
        groupings: List of grouping dicts from groupingsDown.groupings
        result: Flat list of leaf-node dicts (appended to in-place)
        current: Accumulated parent-level fields for this branch
        key_map: Optional dict mapping compound key (e.g., "0_0", "1_0") → flat index
        path: Current nesting path as list of index strings
    """
    if path is None:
        path = []
    for i, grp in enumerate(groupings):
        entry = dict(current)
        label = grp.get("label", grp.get("value", ""))

        # Determine the group field name from the level
        # Level 0 = Account Name, Level 1 = Branch ID (for Report 4)
        sub_groupings = grp.get("groupings", [])
        current_path = path + [str(i)]

        if sub_groupings:
            # This is a parent group (Account Name)
            entry["Account Name"] = label
            _extract_row_groups(sub_groupings, result, entry, key_map, current_path)
        else:
            # This is a leaf group (Branch ID)
            entry["Branch ID"] = label
            compound_key = "_".join(current_path)
            if key_map is not None:
                key_map[compound_key] = len(result)
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
