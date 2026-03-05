"""
HTML generator for OSR Dashboard pages.

Injects processed data into existing HTML files by:
1. Replacing the JS data variable block in <script> tags (split at first `function`)
2. Replacing hardcoded KPI values in HTML body via regex patterns

Existing layout, CSS, and JS functions are preserved.
"""

import json
import logging
import os
import re
from datetime import date

from .config import PROJECT_ROOT

logger = logging.getLogger(__name__)


# ─── JS Data Serialization ──────────────────────────────────────────────────

def _js_value(val) -> str:
    """Serialize a Python value to a JS literal string."""
    if isinstance(val, str):
        return json.dumps(val)
    elif isinstance(val, bool):
        return "true" if val else "false"
    elif isinstance(val, (int, float)):
        return str(val)
    elif isinstance(val, list):
        return json.dumps(val, separators=(",", ":"))
    elif isinstance(val, dict):
        # For repMerchants-style objects, use custom formatting
        return json.dumps(val, separators=(",", ":"))
    return json.dumps(val)


def _build_rep_merchants_js(rep_merchants: dict) -> str:
    """
    Build the repMerchants JS object with the same formatting as the original.
    Each rep gets their own array on separate lines for readability.
    """
    lines = ["var repMerchants={"]
    reps = list(rep_merchants.items())
    for i, (rep_name, merchants) in enumerate(reps):
        # Escape single quotes in rep names
        escaped = rep_name.replace("'", "\\'")
        merchants_json = json.dumps(merchants, separators=(",", ":"))
        comma = "," if i < len(reps) - 1 else ""
        lines.append(f'"{escaped}":{merchants_json}{comma}')
    lines.append("};")
    return "\n".join(lines)


# ─── Monthly Dashboard Generator ────────────────────────────────────────────

def generate_monthly_script_data(data: dict) -> str:
    """
    Generate the complete JS data variable block for a monthly dashboard.

    This replaces everything from after <script> to before the first `function`.
    """
    lines = []

    lines.append(f"var repCredits={_js_value(data['repCredits'])};")
    lines.append(f"var marketData={_js_value(data['marketData'])};")
    lines.append(f"var industryData={_js_value(data['industryData'])};")
    lines.append(f"var marketDataFull={_js_value(data['marketDataFull'])};")
    lines.append(f"var industryDataFull={_js_value(data['industryDataFull'])};")
    lines.append(f"var marketsScope='osr';")
    lines.append(f"var isrData={_js_value(data['isrData'])};")
    lines.append(f"var dailyTrend={_js_value(data['dailyTrend'])};")
    lines.append(f"var topProducers={_js_value(data['topProducers'])};")
    lines.append(f"var PC={_js_value(data['PC'])};")
    lines.append("")
    lines.append(_build_rep_merchants_js(data["repMerchants"]))

    return "\n".join(lines)


def update_monthly_dashboard(filepath: str, data: dict) -> bool:
    """
    Update a monthly dashboard HTML file with new data.

    Args:
        filepath: Path to the HTML file (e.g., feb-2026.html)
        data: Output from monthly_dashboard.process()

    Returns:
        True if file was updated successfully
    """
    if not os.path.exists(filepath):
        logger.error("Monthly dashboard file not found: %s", filepath)
        return False

    html = _read_file(filepath)
    original = html

    # ── Replace script data block ────────────────────────────────────────
    html = _replace_script_data(html, generate_monthly_script_data(data))

    # ── Replace hardcoded HTML KPIs ──────────────────────────────────────
    html = _replace_monthly_html_kpis(html, data)

    # ── Replace hardcoded JS values in function section ──────────────────
    html = _replace_monthly_js_hardcoded(html, data)

    # ── Update last-updated date ─────────────────────────────────────────
    html = re.sub(
        r'(<div class="updated-date">)[^<]+(</div>)',
        rf'\g<1>{data["last_updated"]}\2',
        html
    )

    if html == original:
        logger.info("No changes to %s", filepath)
        return True

    if _validate_html(html):
        _write_file(filepath, html)
        logger.info("Updated %s", filepath)
        return True
    else:
        logger.error("HTML validation failed for %s. File not written.", filepath)
        return False


def _replace_monthly_html_kpis(html: str, data: dict) -> str:
    """Replace hardcoded KPI values in the monthly dashboard HTML body."""
    kpi = data

    # Overview KPIs
    html = _replace_kpi(html, "Total Enrollments", str(kpi["kpi_total"]),
                        sub=f"All sources, {kpi['month_name'][:3]} {kpi['year']}")
    html = _replace_kpi(html, "Credited to OSR", str(kpi["kpi_osr"]),
                        sub=f"{kpi['kpi_credit_pct']}% of total")
    html = _replace_kpi(html, "Funded Volume", kpi["kpi_funded_display"],
                        sub=f"{kpi['kpi_active_merchants']} merchants tracked")
    html = _replace_kpi(html, "Funded Apps", str(kpi["kpi_funded_apps"]),
                        sub=f"of {kpi['kpi_total_apps']} total apps")
    html = _replace_kpi(html, "Conversion Rate", f"{kpi['kpi_conversion']}%",
                        sub="Apps \u2192 Funded")

    # Production KPIs
    html = _replace_kpi(html, "Total Funded", kpi["kpi_funded_display"],
                        sub=f"Across {kpi['kpi_producing_merchants']} producing merchants")
    html = _replace_kpi(html, "Avg Ticket", kpi["kpi_avg_ticket"],
                        sub="Per funded application")
    html = _replace_kpi(html, "Total Applications", str(kpi["kpi_total_apps"]),
                        sub=f"Across {kpi['kpi_active_merchants']} active merchants")

    # Conversion Rate in production tab (same value, different sub)
    # The second instance includes "X of Y apps funded"
    funded_conv_sub = f"{kpi['kpi_funded_apps']} of {kpi['kpi_total_apps']} apps funded"
    html = re.sub(
        r'(Conversion Rate</span><span class="kpi-value">)[^<]+(</span><span class="kpi-sub">)\d+ of \d+ apps funded',
        rf'\g<1>{kpi["kpi_conversion"]}%\g<2>{funded_conv_sub}',
        html
    )

    # Toggle button labels: OSR Credited (N) / All Enrollments (N)
    html = re.sub(r'OSR Credited \(\d+\)', f'OSR Credited ({kpi["kpi_osr"]})', html)
    html = re.sub(r'All Enrollments \(\d+\)', f'All Enrollments ({kpi["kpi_total"]})', html)

    # Total vs Credited stat boxes
    html = re.sub(
        r'(\d+ total new enrollments, \d+ credited)',
        f'{kpi["kpi_total"]} total new enrollments, {kpi["kpi_osr"]} credited',
        html, flags=re.IGNORECASE
    )

    # Stat box: Total New
    html = _replace_stat_box(html, "Total New", str(kpi["kpi_total"]))
    html = _replace_stat_box(html, "OSR Credited", str(kpi["kpi_osr"]),
                             sub=f"{kpi['kpi_credit_pct']}% of total")
    html = _replace_stat_box(html, "Other Sources", str(kpi["kpi_other"]),
                             sub=f"{kpi['kpi_other_pct']}% of total")

    # Daily pace callout
    html = re.sub(
        r'(<strong style="color:#F59E0B">Peak:</strong>)[^<]+(</span>)',
        rf'\1 {kpi["peak_day"]} ({kpi["peak_day_count"]} enrollments)\2',
        html
    )
    html = re.sub(
        r'(<strong style="color:#3B82F6">Avg daily:</strong>)[^<]+(</span>)',
        rf'\1 ~{kpi["avg_daily"]} enrollments/day\2',
        html
    )

    return html


def _replace_monthly_js_hardcoded(html: str, data: dict) -> str:
    """Replace hardcoded values within JS function bodies."""
    kpi = data

    # Product mix doughnut data: [LTO_count, RC_count]
    osr_lto, osr_rc = kpi["osr_product_mix"]
    all_lto, all_rc = kpi["all_product_mix"]

    # OSR product mix in initCharts (the first doughnut data)
    html = re.sub(
        r"(data:\['Lease-to-Own','Retail Contract'\],datasets:\[\{data:)\[\d+,\d+\]",
        rf"\g<1>[{osr_lto},{osr_rc}]",
        html, count=1
    )

    # Product mix legend (OSR): update counts and percentages
    html = _replace_product_legend(html, "ovProductLegend",
                                   osr_lto, osr_rc, kpi["osr_lto_pct"], kpi["osr_rc_pct"],
                                   is_first=True)

    # All-channel product mix in setOverviewScope
    html = re.sub(
        r"(scope==='all'.*?data:\['Lease-to-Own','Retail Contract'\],datasets:\[\{data:)\[\d+,\d+\]",
        rf"\g<1>[{all_lto},{all_rc}]",
        html, count=1, flags=re.DOTALL
    )

    # Funnel items
    fi = kpi["fi"]
    fi_json = json.dumps(fi, separators=(",", ":"))
    html = re.sub(
        r'var fi=\[.*?\];',
        f'var fi={fi_json};',
        html, count=1, flags=re.DOTALL
    )

    # Observations
    obs = kpi["obs"]
    obs_json = json.dumps(obs, separators=(",", ":"), ensure_ascii=False)
    html = re.sub(
        r'var obs=\[.*?\];',
        f'var obs={obs_json};',
        html, count=1, flags=re.DOTALL
    )

    # bars() init call: update max value
    if kpi["marketData"]:
        max_val = kpi["marketData"][0]["v"]
        html = re.sub(
            r"bars\('marketsOverview',marketData\.slice\(0,5\),\d+,",
            f"bars('marketsOverview',marketData.slice(0,5),{max_val},",
            html
        )

    if kpi["isrData"]:
        isr_max = kpi["isrData"][0]["v"]
        html = re.sub(
            r"bars\('isrBars',isrData,\d+,",
            f"bars('isrBars',isrData,{isr_max},",
            html
        )

    return html


# ─── Cohort Tracking Generator ───────────────────────────────────────────────

def update_cohort_tracking(filepath: str, cohorts: dict[str, list],
                           cohort_kpis: dict) -> bool:
    """
    Update cohort-tracking.html with new cohort data.

    Args:
        filepath: Path to cohort-tracking.html
        cohorts: Dict mapping variable names to cohort arrays,
                e.g., {"janCohort": [...], "febCohort": [...]}
        cohort_kpis: Dict with per-cohort KPI summaries
    """
    if not os.path.exists(filepath):
        logger.error("Cohort tracking file not found: %s", filepath)
        return False

    html = _read_file(filepath)

    # Replace each cohort variable
    for var_name, cohort_data in cohorts.items():
        cohort_json = json.dumps(cohort_data, separators=(",", ":"), ensure_ascii=False)
        pattern = rf'var {var_name}=\[.*?\];'
        replacement = f'var {var_name}={cohort_json};'
        html = re.sub(pattern, replacement, html, count=1, flags=re.DOTALL)

    if _validate_html(html):
        _write_file(filepath, html)
        logger.info("Updated %s", filepath)
        return True
    else:
        logger.error("HTML validation failed for %s", filepath)
        return False


# ─── Q1 Enrollment Generator ────────────────────────────────────────────────

def update_q1_enrollment(filepath: str, data: dict) -> bool:
    """
    Update q1-enrollment.html with new enrollment compliance data.

    Args:
        filepath: Path to q1-enrollment.html
        data: Output from q1_enrollment.process()
    """
    if not os.path.exists(filepath):
        logger.error("Q1 enrollment file not found: %s", filepath)
        return False

    html = _read_file(filepath)

    # Replace q1Data variable
    q1_json = json.dumps(data["q1Data"], separators=(",", ":"), ensure_ascii=False)
    html = re.sub(r'var q1Data=\[.*?\];', f'var q1Data={q1_json};', html, count=1, flags=re.DOTALL)

    # Replace hardcoded KPI values in HTML
    html = _replace_q1_kpis(html, data)

    if _validate_html(html):
        _write_file(filepath, html)
        logger.info("Updated %s", filepath)
        return True
    else:
        logger.error("HTML validation failed for %s", filepath)
        return False


def _replace_q1_kpis(html: str, data: dict) -> str:
    """Replace KPI values in q1-enrollment.html."""
    # These KPIs are in stat boxes or similar structures
    # Total Q1 Enrollments
    html = re.sub(
        r'(Q1 Total[^<]*</div>\s*<div class="[^"]*value[^"]*"[^>]*>)\d+',
        rf'\g<1>{data["kpi_total_enrollments"]}',
        html, flags=re.DOTALL
    )

    return html


# ─── Field Activity Generator ────────────────────────────────────────────────

def update_field_activity(filepath: str, data: dict) -> bool:
    """
    Update field-activity.html with new check-in data.

    Args:
        filepath: Path to field-activity.html
        data: Output from field_activity.process()
    """
    if not os.path.exists(filepath):
        logger.error("Field activity file not found: %s", filepath)
        return False

    html = _read_file(filepath)

    # Build the data variable block
    script_data = _build_field_activity_script(data)
    html = _replace_script_data(html, script_data)

    # Replace hardcoded KPIs in HTML body
    html = _replace_field_kpis(html, data)

    if _validate_html(html):
        _write_file(filepath, html)
        logger.info("Updated %s", filepath)
        return True
    else:
        logger.error("HTML validation failed for %s", filepath)
        return False


def _build_field_activity_script(data: dict) -> str:
    """Build the JS data variable block for field-activity.html."""
    lines = []
    lines.append(f"var repActivity={_js_value(data['repActivity'])};")
    lines.append(f"var repStops={_js_value(data['repStops'])};")
    lines.append(f"var dayFilter='all';")
    lines.append(f"var typeFilter='all';")
    lines.append(f"var days={_js_value(data['days'])};")
    lines.append(f"var dayLabels={_js_value(data['dayLabels'])};")
    return "\n".join(lines)


def _replace_field_kpis(html: str, data: dict) -> str:
    """Replace hardcoded KPI values in field-activity.html body."""
    # Total Stops
    html = re.sub(
        r'(Total Stops[^<]*</div>\s*<div[^>]*>)\d+',
        rf'\g<1>{data["kpi_total_stops"]}',
        html, flags=re.DOTALL
    )
    return html


# ─── Index Page Generator ────────────────────────────────────────────────────

def update_index_page(filepath: str, data: dict) -> bool:
    """
    Update index.html with new aggregated values.

    Args:
        filepath: Path to index.html
        data: Output from index_page.process()
    """
    if not os.path.exists(filepath):
        logger.error("Index file not found: %s", filepath)
        return False

    html = _read_file(filepath)

    # ── YTD Summary ──────────────────────────────────────────────────────
    # Total Enrollments
    html = _replace_sb_value(html, "#3B82F6", str(data["ytd_total_enrollments"]), "All channels")
    # OSR Credited
    html = _replace_sb_value(html, "#10B981", str(data["ytd_osr_credited"]), data["ytd_credit_pct"])
    # Funded Volume
    html = _replace_sb_value(html, "#F59E0B", data["ytd_funded_display"], data["ytd_funded_sub"])
    # Months Tracked
    html = _replace_sb_value(html, "#8B5CF6", str(data["ytd_months_tracked"]), data["ytd_months_sub"])

    # ── Commission Tracking Card ─────────────────────────────────────────
    cohort = data.get("cohort", {})
    active = cohort.get("active_cohort", {})
    baseline = cohort.get("baseline_cohort", {})

    if active:
        # Active cohort funded (unique green in Commission Tracking section)
        html = _replace_nth_mk_value(html, 0, active.get("total_funded_display", "$0"),
                                     color="#10B981", section_start="Commission Tracking")
    if baseline:
        # Baseline cohort funded (unique blue in Commission Tracking section)
        html = _replace_nth_mk_value(html, 0, baseline.get("total_funded_display", "$0"),
                                     color="#3B82F6", section_start="Commission Tracking")
    if active:
        # At $15K Target (first amber in Commission Tracking section)
        html = _replace_nth_mk_value(html, 0, active.get("at_target_display", "0 / 0"),
                                     color="#F59E0B", section_start="Commission Tracking")

    # ── Q1 Enrollment Compliance Card ────────────────────────────────────
    # Each color is unique within the Q1 Enrollment section, so n=0 for all
    # Q1 Total
    html = _replace_nth_mk_value(html, 0, str(data["q1_total"]),
                                 color="#8B5CF6", section_start="Q1 Enrollment")
    # At 30 Target
    html = _replace_nth_mk_value(html, 0, data["q1_at_target"],
                                 color="#10B981", section_start="Q1 Enrollment")
    # 10/mo Flags
    html = _replace_nth_mk_value(html, 0, str(data["q1_months_under_10"]),
                                 color="#F59E0B", section_start="Q1 Enrollment")
    # Days Remaining
    html = _replace_nth_mk_value(html, 0, data["q1_days_remaining"],
                                 color="#06B6D4", section_start="Q1 Enrollment")

    # ── Field Activity Card ──────────────────────────────────────────────
    # Each color is unique within the Field Activity section, so n=0 for all
    # Use ">Field Activity<" to avoid matching the HTML comment <!-- Field Activity -->
    html = _replace_nth_mk_value(html, 0, str(data["field_total_stops"]),
                                 color="#06B6D4", section_start=">Field Activity<")
    html = _replace_nth_mk_value(html, 0, str(data["field_existing"]),
                                 color="#3B82F6", section_start=">Field Activity<")
    html = _replace_nth_mk_value(html, 0, str(data["field_prospect"]),
                                 color="#F59E0B", section_start=">Field Activity<")
    html = _replace_nth_mk_value(html, 0, str(data["field_reps_active"]),
                                 color="#10B981", section_start=">Field Activity<")

    if _validate_html(html):
        _write_file(filepath, html)
        logger.info("Updated index.html")
        return True
    else:
        logger.error("HTML validation failed for index.html")
        return False


# ─── Core Utilities ──────────────────────────────────────────────────────────

def _replace_script_data(html: str, new_data: str) -> str:
    """
    Replace the data variable section of the main <script> block.

    Finds the last <script> tag (the one with data, not CDN imports),
    and replaces everything from after <script> to before the first `function` keyword.
    """
    # Find the last <script> tag that's not a src= import
    script_starts = [m.end() for m in re.finditer(r'<script>(?!\s*$)', html)]

    if not script_starts:
        logger.error("No <script> tags found in HTML")
        return html

    # Use the last inline script block
    script_start = script_starts[-1]

    # Find the first `function ` after the script start
    func_match = re.search(r'\nfunction ', html[script_start:])
    if not func_match:
        logger.error("No 'function' keyword found after <script>")
        return html

    func_pos = script_start + func_match.start()

    # Replace the data section
    html = html[:script_start] + "\n" + new_data + "\n" + html[func_pos:]

    return html


def _replace_kpi(html: str, label: str, value: str, sub: str = None) -> str:
    """Replace a KPI value by its label in the HTML."""
    # Pattern: <label>LABEL</span><span class="kpi-value">VALUE</span>
    pattern = rf'({re.escape(label)}</span><span class="kpi-value">)[^<]+(</span>)'
    html = re.sub(pattern, rf'\g<1>{value}\2', html, count=1)

    if sub:
        # Also update the sub-text if found right after
        pattern = rf'({re.escape(label)}.*?<span class="kpi-sub">)[^<]+(</span>)'
        html = re.sub(pattern, rf'\g<1>{sub}\2', html, count=1, flags=re.DOTALL)

    return html


def _replace_stat_box(html: str, label: str, value: str, sub: str = None) -> str:
    """Replace a stat-box value by its label."""
    pattern = rf'({re.escape(label)}</div><div class="stat-box-value"[^>]*>)[^<]+(</div>)'
    html = re.sub(pattern, rf'\g<1>{value}\2', html, count=1)
    if sub:
        pattern = rf'({re.escape(label)}.*?<div class="stat-box-sub">)[^<]+(</div>)'
        html = re.sub(pattern, rf'\g<1>{sub}\2', html, count=1, flags=re.DOTALL)
    return html


def _replace_sb_value(html: str, color: str, value: str, sub: str) -> str:
    """Replace a summary bar value on index.html by its color."""
    # Pattern: <div class="sb-value" style="color:COLOR">VALUE</div>
    pattern = rf'(<div class="sb-value" style="color:{re.escape(color)}">)[^<]+(</div>)'
    html = re.sub(pattern, rf'\g<1>{value}\2', html, count=1)
    # Also update sub text
    pattern = rf'(<div class="sb-value" style="color:{re.escape(color)}">[^<]+</div>\s*<div class="sb-sub">)[^<]+(</div>)'
    html = re.sub(pattern, rf'\g<1>{sub}\2', html, count=1, flags=re.DOTALL)
    return html


def _replace_nth_mk_value(html: str, n: int, value: str, color: str = None,
                           section_start: str = None) -> str:
    """
    Replace the nth mk-value in a section of index.html.

    Args:
        html: Full HTML string
        n: 0-based index of the mk-value to replace within the section
        value: New value string
        color: Color of the mk-value (for additional specificity)
        section_start: Text to find the start of the section
    """
    if section_start:
        section_idx = html.find(section_start)
        if section_idx == -1:
            return html
        # Find the next section boundary (year-group div or h2)
        # index.html uses <div class="year-title"> for sections, not <h2>
        next_section = -1
        for boundary in ['class="year-title"', 'class="year-group"', '<h2']:
            pos = html.find(boundary, section_idx + len(section_start))
            if pos != -1:
                # Back up to the start of the containing tag
                tag_start = html.rfind('<', section_idx, pos)
                if tag_start != -1:
                    pos = tag_start
                if next_section == -1 or pos < next_section:
                    next_section = pos
        if next_section == -1:
            section = html[section_idx:]
            offset = section_idx
        else:
            section = html[section_idx:next_section]
            offset = section_idx
    else:
        section = html
        offset = 0

    # Find all mk-value divs in the section
    if color:
        pattern = rf'<div class="mk-value" style="color:{re.escape(color)}">[^<]+</div>'
    else:
        pattern = r'<div class="mk-value"[^>]*>[^<]+</div>'

    matches = list(re.finditer(pattern, section))
    logger.debug("_replace_nth_mk_value: section_start=%s, color=%s, n=%d, "
                 "section_len=%d, matches=%d, next_section_pos=%s",
                 section_start, color, n, len(section), len(matches),
                 next_section if section_start else "N/A")
    if n < len(matches):
        match = matches[n]
        # Build replacement
        old = match.group()
        new = re.sub(r'>([^<]+)<', f'>{value}<', old)
        logger.debug("Replacing: %s → %s", old[:60], new[:60])
        abs_start = offset + match.start()
        abs_end = offset + match.end()
        html = html[:abs_start] + new + html[abs_end:]

    return html


def _replace_product_legend(html: str, legend_id: str,
                            lto_count: int, rc_count: int,
                            lto_pct: float, rc_pct: float,
                            is_first: bool = True) -> str:
    """Replace product mix legend values."""
    # This is complex inline HTML, so we do targeted number replacements
    # within the specific legend div
    return html  # Product legend is rebuilt by JS, so static HTML just needs initial values


def _validate_html(html: str) -> bool:
    """Basic validation that the HTML is not broken."""
    checks = [
        ("</html>" in html, "Missing </html>"),
        ("<script>" in html or '<script ' in html, "Missing <script>"),
        ("</script>" in html, "Missing </script>"),
        (html.count("<script") == html.count("</script>"), "Mismatched script tags"),
    ]
    for check, msg in checks:
        if not check:
            logger.error("Validation failed: %s", msg)
            return False
    return True


def _read_file(filepath: str) -> str:
    """Read a file and return its contents."""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def _write_file(filepath: str, content: str) -> None:
    """Write content to a file."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("Wrote %d bytes to %s", len(content), filepath)
