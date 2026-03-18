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

from .config import PROJECT_ROOT, MONTH_NAMES, MONTH_ABBREV

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
        r'(<strong style="color:#FBBF24">Peak:</strong>)[^<]+(</span>)',
        rf'\1 {kpi["peak_day"]} ({kpi["peak_day_count"]} enrollments)\2',
        html
    )
    html = re.sub(
        r'(<strong style="color:#5B9BFF">Avg daily:</strong>)[^<]+(</span>)',
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
                           cohort_kpis: dict,
                           cohort_configs: list = None) -> bool:
    """
    Update cohort-tracking.html with new cohort data.

    Args:
        filepath: Path to cohort-tracking.html
        cohorts: Dict mapping variable names to cohort arrays,
                e.g., {"janCohort": [...], "febCohort": [...]}
        cohort_kpis: Dict with per-cohort KPI summaries
        cohort_configs: List of cohort config dicts for the cohortConfig JS variable
    """
    if not os.path.exists(filepath):
        logger.error("Cohort tracking file not found: %s", filepath)
        return False

    html = _read_file(filepath)

    # Replace each cohort data variable
    for var_name, cohort_data in cohorts.items():
        cohort_json = json.dumps(cohort_data, separators=(",", ":"), ensure_ascii=False)
        pattern = rf'var {var_name}=\[.*?\];'
        replacement = f'var {var_name}={cohort_json};'
        if re.search(pattern, html, flags=re.DOTALL):
            html = re.sub(pattern, replacement, html, count=1, flags=re.DOTALL)
        else:
            # New cohort variable — insert before activeTab declaration
            insert_pos = html.find('var activeTab=')
            if insert_pos != -1:
                html = html[:insert_pos] + replacement + '\n' + html[insert_pos:]
                logger.info("Inserted new cohort variable: %s", var_name)

    # Inject/update cohortConfig variable
    if cohort_configs:
        config_json = json.dumps(cohort_configs, separators=(",", ":"), ensure_ascii=False)
        if re.search(r'var cohortConfig=\[.*?\];', html, flags=re.DOTALL):
            html = re.sub(r'var cohortConfig=\[.*?\];',
                          f'var cohortConfig={config_json};',
                          html, count=1, flags=re.DOTALL)
        else:
            # Insert at the start of the script
            script_pos = html.find('<script>') + len('<script>')
            html = html[:script_pos] + f'\nvar cohortConfig={config_json};\n' + html[script_pos:]

        # Update activeTab to match first (active) cohort
        active_id = cohort_configs[0]["id"]
        html = re.sub(r"var activeTab='[^']*'",
                      f"var activeTab='{active_id}'", html)

        # Regenerate tab HTML
        tabs_html = _generate_cohort_tabs_html(cohort_configs)
        html = re.sub(
            r'(<div class="tabs" id="cohortTabs">)\s*.*?\s*(</div>\s*\n\s*<div id="kpis">)',
            rf'\1\n{tabs_html}\n\2',
            html, count=1, flags=re.DOTALL
        )

    if _validate_html(html):
        _write_file(filepath, html)
        logger.info("Updated %s", filepath)
        return True
    else:
        logger.error("HTML validation failed for %s", filepath)
        return False


def _generate_cohort_tabs_html(configs: list) -> str:
    """Generate the tab button HTML for cohort tracking."""
    # First config entry is the default active tab
    default_id = configs[0]["id"] if configs else ""

    tabs = []
    for cfg in configs:
        tab_class = "tab"
        if cfg["id"] == default_id:
            tab_class += " active"  # Currently selected tab
        elif cfg.get("type") == "baseline":
            tab_class += " tab-dim"

        tag_text = ""
        tag_style = ""
        if cfg["type"] == "new":
            tag_text = "New"
            tag_style = ' style="background:rgba(167,139,250,.18);color:#A78BFA"'
        elif cfg["type"] == "active":
            tag_text = "Active"
        elif cfg["type"] == "baseline":
            tag_text = "Baseline"

        cid = cfg["id"]
        label = cfg["label"]
        tab_html = f'<div class="{tab_class}" data-tab="{cid}" onclick="switchTab(\'{cid}\')">{label}'
        if tag_text:
            tab_html += f' <span class="tag"{tag_style}>{tag_text}</span>'
        tab_html += '</div>'
        tabs.append(tab_html)

    return "\n".join(tabs)


# ─── Quarterly Enrollment Generator ──────────────────────────────────────────

def update_q1_enrollment(filepath: str, data: dict) -> bool:
    """
    Update a quarterly enrollment HTML file with new compliance data.

    Args:
        filepath: Path to q{N}-enrollment.html
        data: Output from q1_enrollment.process()
    """
    if not os.path.exists(filepath):
        logger.error("Quarterly enrollment file not found: %s", filepath)
        return False

    html = _read_file(filepath)

    quarter_months = data.get("quarter_months", [1, 2, 3])
    quarter_num = (quarter_months[0] - 1) // 3 + 1
    year = data.get("year", 2026)

    # Generate and inject quarterConfig
    config_js = _build_quarter_config_js(data)
    html = re.sub(r'var quarterConfig=\{.*?\};',
                  f'var quarterConfig={config_js};',
                  html, count=1, flags=re.DOTALL)

    # Replace q1Data variable
    q1_json = json.dumps(data["q1Data"], separators=(",", ":"), ensure_ascii=False)
    html = re.sub(r'var q1Data=\[.*?\];', f'var q1Data={q1_json};',
                  html, count=1, flags=re.DOTALL)

    # Update dynamic text: title, heading, footer, badge year
    html = re.sub(r'Q\d \d{4} Enrollment Tracker',
                  f'Q{quarter_num} {year} Enrollment Tracker', html)
    html = re.sub(r'Q\d Enrollment Compliance',
                  f'Q{quarter_num} Enrollment Compliance', html)
    html = re.sub(r'Q\d \d{4} Enrollment Compliance Tracker',
                  f'Q{quarter_num} {year} Enrollment Compliance Tracker', html)
    html = re.sub(r'(<span class="badge">)\d{4}(</span>)',
                  rf'\g<1>{year}\2', html)

    # Replace hardcoded KPI values in HTML
    html = _replace_q1_kpis(html, data)

    if _validate_html(html):
        _write_file(filepath, html)
        logger.info("Updated %s", filepath)
        return True
    else:
        logger.error("HTML validation failed for %s", filepath)
        return False


def _build_quarter_config_js(data: dict) -> str:
    """Build the quarterConfig JS object from processor data."""
    quarter_months = data.get("quarter_months", [1, 2, 3])
    year = data.get("year", 2026)
    quarter_num = (quarter_months[0] - 1) // 3 + 1

    months = []
    for m in quarter_months:
        months.append({
            "key": MONTH_ABBREV[m],
            "label": MONTH_NAMES[m],
            "num": m,
        })

    config = {"num": quarter_num, "year": year, "months": months}
    return json.dumps(config, separators=(",", ":"))


def _replace_q1_kpis(html: str, data: dict) -> str:
    """Replace KPI values in the quarterly enrollment HTML."""
    quarter_months = data.get("quarter_months", [1, 2, 3])
    quarter_num = (quarter_months[0] - 1) // 3 + 1
    current_month = data.get("kpi_current_month", "")

    # Total Q enrollments — update label and value
    html = re.sub(r'Total Q\d Enrollments',
                  f'Total Q{quarter_num} Enrollments', html)
    html = re.sub(
        r'(Total Q\d Enrollments</div><div class="kpi-v"[^>]*>)[^<]+',
        rf'\g<1>{data["kpi_total_enrollments"]}',
        html
    )

    # Reps at 30
    html = re.sub(
        r'(Reps at 30</div><div class="kpi-v"[^>]*>)[^<]+',
        rf'\g<1>{data["kpi_at_target"]}',
        html
    )

    # Months Under 10
    html = re.sub(
        r'(Months Under 10</div><div class="kpi-v"[^>]*>)[^<]+',
        rf'\g<1>{data["kpi_months_under_10"]}',
        html
    )

    # Month Remaining — update label and value
    if current_month:
        html = re.sub(r'\w+ Remaining</div><div class="kpi-v"',
                      f'{current_month} Remaining</div><div class="kpi-v"', html)
        days_match = re.search(r'(\d+)', data.get("kpi_days_remaining", "0 days"))
        if days_match:
            html = re.sub(
                r'(\w+ Remaining</div><div class="kpi-v"[^>]*>)[^<]+',
                rf'\g<1>{days_match.group(1)}',
                html
            )

    # Update KPI sub text for completed months
    completed_months = []
    for m in quarter_months:
        from datetime import date as dt_date
        today = dt_date.today()
        if data.get("year", 2026) < today.year or \
           (data.get("year", 2026) == today.year and m < today.month):
            completed_months.append(MONTH_NAMES[m][:3])
    if completed_months:
        months_sub = "+".join(completed_months)
        html = re.sub(r'Across all reps \([^)]+\)',
                      f'Across all reps ({months_sub})', html)

    return html


def create_quarterly_enrollment_page(quarter_num: int, year: int,
                                      output_dir: str = None) -> str:
    """
    Create a new quarterly enrollment page from the template.

    Uses q1-enrollment.html as the base template (it has the config-driven
    render function), updates Q number and year references.

    Returns the path to the created file, or None on failure.
    """
    # Find the best template: q1-enrollment.html or most recent existing quarter
    template_path = os.path.join(PROJECT_ROOT, "q1-enrollment.html")
    if not os.path.exists(template_path):
        # Try the previous quarter
        for q in range(quarter_num - 1, 0, -1):
            candidate = os.path.join(PROJECT_ROOT, f"q{q}-enrollment.html")
            if os.path.exists(candidate):
                template_path = candidate
                break
        else:
            logger.error("No quarterly enrollment template found")
            return None

    target_dir = output_dir or PROJECT_ROOT
    target_path = os.path.join(target_dir, f"q{quarter_num}-enrollment.html")

    html = _read_file(template_path)

    # Replace Q number and year references
    html = re.sub(r'Q\d \d{4} Enrollment Tracker',
                  f'Q{quarter_num} {year} Enrollment Tracker', html)
    html = re.sub(r'Q\d Enrollment Compliance',
                  f'Q{quarter_num} Enrollment Compliance', html)
    html = re.sub(r'Q\d \d{4} Enrollment Compliance Tracker',
                  f'Q{quarter_num} {year} Enrollment Compliance Tracker', html)
    html = re.sub(r'(<span class="badge">)\d{4}',
                  rf'\g<1>{year}', html)

    _write_file(target_path, html)
    logger.info("Created quarterly enrollment page: %s", target_path)
    return target_path


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
    """Build the JS data variable block for field-activity.html.

    Includes calendar state initialization so it survives data replacement.
    The _replace_script_data() function replaces everything from <script> to
    the first `function` keyword, so the calendar init IIFE must live here.
    """
    lines = []
    lines.append(f"var repActivity={_js_value(data['repActivity'])};")
    lines.append(f"var repStops={_js_value(data['repStops'])};")
    lines.append(f"var rangeStart=null;")
    lines.append(f"var rangeEnd=null;")
    lines.append(f"var typeFilter='all';")
    lines.append(f"var days={_js_value(data['days'])};")
    lines.append(f"var dayLabels={_js_value(data['dayLabels'])};")
    lines.append("")
    # Calendar state — must be in data block because _replace_script_data
    # replaces everything before the first `function` keyword.
    lines.append("// ── Calendar state ──────────────────────────────────────────")
    lines.append("var calYear, calMonth;")
    lines.append("(function initCal(){")
    lines.append("  if(days.length){")
    lines.append("    var p=days[0].split('/');")
    lines.append("    calMonth=parseInt(p[0])-1;")
    lines.append("    calYear=parseInt(p[2]);")
    lines.append("  } else {")
    lines.append("    var now=new Date();")
    lines.append("    calMonth=now.getMonth();")
    lines.append("    calYear=now.getFullYear();")
    lines.append("  }")
    lines.append("})();")
    return "\n".join(lines)


def _replace_field_kpis(html: str, data: dict) -> str:
    """Replace hardcoded KPI values and header in field-activity.html.

    The calendar component is rendered client-side from the days/dayLabels
    data variables, so no HTML replacement is needed for filters.
    """
    from datetime import datetime

    # Update header subtitle with date range
    month_range = data.get("kpi_month_range", "N/A")
    if month_range and month_range != "N/A":
        parts = month_range.split(" - ")
        if len(parts) == 2:
            start_short = "/".join(parts[0].split("/")[:2])
            end_short = "/".join(parts[1].split("/")[:2])
            year = parts[1].split("/")[-1] if "/" in parts[1] else "2026"
            sub_text = f"Maps check-ins &middot; {start_short} &ndash; {end_short}, {year}"
        else:
            sub_text = f"Maps check-ins &middot; {month_range}"
    else:
        sub_text = "Maps check-ins &middot; No data"

    html = re.sub(
        r'(<div class="header-sub">).*?(</div>)',
        rf'\1{sub_text}\2',
        html
    )

    # ── KPI values ────────────────────────────────────────────────────────
    total = data["kpi_total_stops"] or 1
    existing = data["kpi_existing"]
    prospect = data["kpi_prospect"]
    existing_pct = round(existing / total * 100) if total else 0
    prospect_pct = round(prospect / total * 100) if total else 0
    reps_count = int(data["kpi_reps_active"].split("/")[0].strip()) if "/" in str(data["kpi_reps_active"]) else 1
    avg_per_rep = round(data["kpi_total_stops"] / max(reps_count, 1), 1)

    # Total Stops value
    html = re.sub(
        r'(Total Stops[^<]*</div>\s*<div[^>]*>)\d+',
        rf'\g<1>{data["kpi_total_stops"]}',
        html, flags=re.DOTALL
    )

    # Avg per day sub-label (value may be int or float like "83.0")
    html = re.sub(
        r'[\d.]+ avg / day',
        f'{data["kpi_avg_per_day"]} avg / day',
        html
    )

    # Existing Merchants value
    html = re.sub(
        r'(Existing Merchants[^<]*</div>\s*<div[^>]*>)\d+',
        rf'\g<1>{existing}',
        html, flags=re.DOTALL
    )

    # Existing Merchants % sub-label (appears right after Existing value)
    html = re.sub(
        r'(\d+% of stops</div>\s*</div>\s*<div class="kpi-card">\s*<div class="kpi-label">Prospects)',
        f'{existing_pct}% of stops</div>\n  </div>\n  <div class="kpi-card">\n    <div class="kpi-label">Prospects',
        html, flags=re.DOTALL
    )

    # Prospects value
    html = re.sub(
        r'(Prospects[^<]*</div>\s*<div[^>]*>)\d+',
        rf'\g<1>{prospect}',
        html, flags=re.DOTALL
    )

    # Prospects % sub-label (appears right after Prospects value)
    html = re.sub(
        r'(\d+% of stops</div>\s*</div>\s*<div class="kpi-card">\s*<div class="kpi-label">Reps Active)',
        f'{prospect_pct}% of stops</div>\n  </div>\n  <div class="kpi-card">\n    <div class="kpi-label">Reps Active',
        html, flags=re.DOTALL
    )

    # Reps Active value
    html = re.sub(
        r'(Reps Active[^<]*</div>\s*<div[^>]*>)\d+',
        rf'\g<1>{reps_count}',
        html, flags=re.DOTALL
    )

    # Reps Active sub-label (avg stops per rep)
    html = re.sub(
        r'[\d.]+ avg stops / rep',
        f'{avg_per_rep} avg stops / rep',
        html
    )

    return html


# ─── Index Page Generator ────────────────────────────────────────────────────

_MONTH_ORDER = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

_ARROW_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" '
              'stroke-width="2.5" stroke="currentColor"><path stroke-linecap="round" '
              'stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5"/></svg>')


def _generate_month_card_html(card: dict, tag_html: str = "") -> str:
    """Generate HTML for a single month dashboard card."""
    key = card["key"]  # e.g., "feb-2026"
    href = f"{key}.html"

    top_rep = card.get("top_rep_name", "N/A")
    top_rep_count = card.get("top_rep_count", 0)
    top_market = card.get("top_market_name", "N/A")
    top_market_count = card.get("top_market_count", 0)

    top_rep_display = f"{top_rep} ({top_rep_count})" if top_rep != "N/A" and top_rep_count > 0 else "N/A"
    top_market_display = f"{top_market} ({top_market_count})" if top_market != "N/A" and top_market_count > 0 else "N/A"

    tag_line = f'\n            {tag_html}' if tag_html else ""

    return f"""        <a href="{href}" class="month-card">
          <div class="month-header">
            <div class="month-name">{card["month_name"]}</div>{tag_line}
          </div>
          <div class="month-kpis">
            <div class="mk">
              <div class="mk-label">Enrollments</div>
              <div class="mk-value" style="color:#5B9BFF">{card["kpi_total"]}</div>
            </div>
            <div class="mk">
              <div class="mk-label">OSR Credited</div>
              <div class="mk-value" style="color:#2DD4A0">{card["kpi_osr"]}</div>
            </div>
            <div class="mk">
              <div class="mk-label">Funded Volume</div>
              <div class="mk-value" style="color:#FBBF24">{card["kpi_funded_short"]}</div>
            </div>
            <div class="mk">
              <div class="mk-label">Conversion</div>
              <div class="mk-value" style="color:#A78BFA">{card["kpi_conversion"]}</div>
            </div>
          </div>
          <div class="month-footer">
            <div class="month-detail">Top rep: <span>{top_rep_display}</span> \u00b7 Top market: <span>{top_market_display}</span></div>
            <div class="month-arrow">View {_ARROW_SVG}</div>
          </div>
        </a>"""


def _generate_month_cards_html(month_cards: list) -> str:
    """Generate all month card HTML blocks, sorted newest-first."""
    if not month_cards:
        return ""

    # Sort newest-first by year desc, then month number desc
    def sort_key(card):
        abbrev = card["key"].split("-")[0]
        month_num = _MONTH_ORDER.get(abbrev, 0)
        return (card.get("year", 2026), month_num)

    sorted_cards = sorted(month_cards, key=sort_key, reverse=True)

    cards_html = []
    for i, card in enumerate(sorted_cards):
        if i == 0:
            # Newest card gets "Latest" badge
            tag = '<span class="month-tag tag-latest">Latest</span>'
        elif card["key"] == "jan-2026":
            # January 2026 always gets "Baseline" badge
            tag = '<span class="month-tag" style="background:#3D5170;color:#A8B8CC">Baseline</span>'
        else:
            tag = ""

        cards_html.append(_generate_month_card_html(card, tag))

    return "\n\n" + "\n\n".join(cards_html) + "\n"


def _replace_month_grid(html: str, month_cards_html: str) -> str:
    """Replace the inner content of the monthGrid div with generated cards."""
    grid_open = '<div class="month-grid" id="monthGrid">'
    grid_marker = '<!-- Show/hide toggle'

    grid_start = html.find(grid_open)
    if grid_start == -1:
        logger.warning("monthGrid div not found in index.html")
        return html

    content_start = grid_start + len(grid_open)
    marker_pos = html.find(grid_marker, content_start)
    if marker_pos == -1:
        logger.warning("Show/hide toggle comment not found in index.html")
        return html

    # Find the closing </div> right before the marker
    close_div_pos = html.rfind('</div>', content_start, marker_pos)
    if close_div_pos == -1:
        logger.warning("Closing </div> for monthGrid not found")
        return html

    html = (html[:content_start] +
            month_cards_html +
            "\n      " + html[close_div_pos:])

    logger.info("Replaced monthGrid contents with %d generated cards",
                month_cards_html.count('class="month-card"'))
    return html


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
    html = _replace_sb_value(html, "#5B9BFF", str(data["ytd_total_enrollments"]), "All channels")
    # OSR Credited
    html = _replace_sb_value(html, "#2DD4A0", str(data["ytd_osr_credited"]), data["ytd_credit_pct"])
    # Funded Volume
    html = _replace_sb_value(html, "#FBBF24", data["ytd_funded_display"], data["ytd_funded_sub"])
    # Months Tracked
    html = _replace_sb_value(html, "#A78BFA", str(data["ytd_months_tracked"]), data["ytd_months_sub"])

    # ── Enrollment Production Tracking Card ─────────────────────────────────────────
    cohort = data.get("cohort", {})
    active = cohort.get("active_cohort", {})
    baseline = cohort.get("baseline_cohort", {})

    if active:
        # Active cohort funded (unique green in Enrollment Production Tracking section)
        html = _replace_nth_mk_value(html, 0, active.get("total_funded_display", "$0"),
                                     color="#2DD4A0", section_start="Enrollment Production Tracking")
    if baseline:
        # Baseline cohort funded (unique blue in Enrollment Production Tracking section)
        html = _replace_nth_mk_value(html, 0, baseline.get("total_funded_display", "$0"),
                                     color="#5B9BFF", section_start="Enrollment Production Tracking")
    if active:
        # At $15K Target (first amber in Enrollment Production Tracking section)
        html = _replace_nth_mk_value(html, 0, active.get("at_target_display", "0 / 0"),
                                     color="#FBBF24", section_start="Enrollment Production Tracking")

    # ── Q1 Enrollment Compliance Card ────────────────────────────────────
    # Find the current quarter label in the HTML (may be Q1, Q2, etc.)
    quarter_num = data.get("quarter_num", 1)
    quarter_filename = data.get("quarter_filename", "q1-enrollment.html")
    quarter_current_month = data.get("quarter_current_month", "")

    q_match = re.search(r'Q(\d) Enrollment', html)
    q_section = q_match.group() if q_match else f"Q{quarter_num} Enrollment"

    # Update KPI values (using current Q-section text for matching)
    html = _replace_nth_mk_value(html, 0, str(data["q1_total"]),
                                 color="#A78BFA", section_start=q_section)
    html = _replace_nth_mk_value(html, 0, data["q1_at_target"],
                                 color="#2DD4A0", section_start=q_section)
    html = _replace_nth_mk_value(html, 0, str(data["q1_months_under_10"]),
                                 color="#FBBF24", section_start=q_section)
    html = _replace_nth_mk_value(html, 0, data["q1_days_remaining"],
                                 color="#22D3EE", section_start=q_section)

    # Dynamically update Q-number labels, href, and month name
    html = re.sub(r'href="q\d-enrollment\.html"',
                  f'href="{quarter_filename}"', html)
    html = re.sub(r'Q\d Enrollment Compliance',
                  f'Q{quarter_num} Enrollment Compliance', html)
    html = re.sub(r'Q\d Total', f'Q{quarter_num} Total', html)
    if quarter_current_month:
        html = re.sub(r'(\w+) Remaining', f'{quarter_current_month[:3]} Remaining', html)

    # ── Field Activity Card ──────────────────────────────────────────────
    # Update card title to "This Month's Check-Ins"
    html = re.sub(
        r"This Week's Check-Ins",
        "This Month's Check-Ins",
        html
    )

    # Update detail line with date range and avg/day
    # Note: The HTML uses literal Unicode · (U+00B7) and – (U+2013), not HTML entities
    field_range = data.get("field_month_range", "N/A")
    field_avg = data.get("field_avg_per_day", 0)
    if field_range and field_range != "N/A":
        parts = field_range.split(" - ")
        if len(parts) == 2:
            start_short = "/".join(parts[0].split("/")[:2])
            end_short = "/".join(parts[1].split("/")[:2])
            range_text = f"{start_short}\u2013{end_short}"
        else:
            range_text = field_range
    else:
        range_text = "No data"
    html = re.sub(
        r'Maps check-ins[^<]*<span>[^<]*</span>',
        f'Maps check-ins \u00b7 {range_text} \u00b7 <span>{field_avg} avg/day</span>',
        html
    )

    # Each color is unique within the Field Activity section, so n=0 for all
    # Use ">Field Activity<" to avoid matching the HTML comment <!-- Field Activity -->
    html = _replace_nth_mk_value(html, 0, str(data["field_total_stops"]),
                                 color="#22D3EE", section_start=">Field Activity<")
    html = _replace_nth_mk_value(html, 0, str(data["field_existing"]),
                                 color="#5B9BFF", section_start=">Field Activity<")
    html = _replace_nth_mk_value(html, 0, str(data["field_prospect"]),
                                 color="#FBBF24", section_start=">Field Activity<")
    html = _replace_nth_mk_value(html, 0, str(data["field_reps_active"]),
                                 color="#2DD4A0", section_start=">Field Activity<")

    # ── Rep Leaderboard ─────────────────────────────────────────────────────
    scorecard = data.get("rep_scorecard", [])
    if scorecard:
        scorecard_html = _generate_scorecard_table(
            scorecard,
            data.get("scorecard_month", ""),
            data.get("scorecard_year", 2026),
        )
        html = _replace_between_markers(html, "Scorecard Data", scorecard_html)

    # ── ISR Leaderboard ──────────────────────────────────────────────────
    isr_scorecard = data.get("isr_scorecard", [])
    if isr_scorecard:
        isr_html = _generate_isr_scorecard_table(isr_scorecard)
        html = _replace_between_markers(html, "ISR Scorecard Data", isr_html)

    # ── Month Cards ──────────────────────────────────────────────────────
    month_cards_html = _generate_month_cards_html(data.get("month_cards", []))
    if month_cards_html:
        html = _replace_month_grid(html, month_cards_html)

    if _validate_html(html):
        _write_file(filepath, html)
        logger.info("Updated index.html")
        return True
    else:
        logger.error("HTML validation failed for index.html")
        return False


# ─── Analytics Page Generator ────────────────────────────────────────────────

def generate_analytics_script_data(data: dict) -> str:
    """
    Generate the JS data variable block for analytics.html.

    Replaces everything from <script> to the first `function` keyword,
    so this must also include the chart config constants (charts, PC, ttStyle,
    Chart.defaults) that live between the data block and the first function.
    """
    lines = []

    # monthlyKPIs
    lines.append(f"var monthlyKPIs={_js_value(data['monthlyKPIs'])};")
    lines.append("")

    # repTrends
    lines.append(f"var repTrends={_js_value(data['repTrends'])};")
    lines.append("")

    # Daily pace
    lines.append(f"var dailyPaceCurrent={_js_value(data['dailyPaceCurrent'])};")
    lines.append("")
    lines.append(f"var dailyPacePrevious={_js_value(data['dailyPacePrevious'])};")
    lines.append("")

    # Market trends
    lines.append(f"var marketTrends={_js_value(data['marketTrends'])};")
    lines.append("")

    # Cohort reps — one variable per cohort
    for var_name, reps_array in sorted(data.get("cohortReps", {}).items()):
        lines.append(f"var {var_name}={_js_value(reps_array)};")
    lines.append("")

    # Funnel data
    lines.append(f"var funnelData={_js_value(data['funnelData'])};")
    lines.append("")

    # Metadata
    lines.append(f"var bizDaysLeft={data['bizDaysLeft']};")
    lines.append(f"var currentMonthLabel={json.dumps(data['currentMonthLabel'])};")
    lines.append(f"var previousMonthLabel={json.dumps(data['previousMonthLabel'])};")
    lines.append("")

    # Chart config constants (must be included because _replace_script_data
    # replaces everything up to the first `function` keyword)
    lines.append("/* ============================================================")
    lines.append("   FUNCTIONS — Pipeline preserves everything below")
    lines.append("   ============================================================ */")
    lines.append("")
    lines.append("var charts={};")
    lines.append('var PC=["#3B82F6","#10B981","#F59E0B","#EF4444","#8B5CF6",'
                 '"#06B6D4","#EC4899","#F97316","#14B8A6","#A855F7","#6366F1","#84CC16"];')
    lines.append("var ttStyle={backgroundColor:'#293852',borderColor:'#3D5170',"
                 "borderWidth:1,titleColor:'#A8B8CC',bodyColor:'#F1F5F9',"
                 "padding:12,cornerRadius:10};")
    lines.append("")
    lines.append("Chart.defaults.color='#8494AB';")
    lines.append("Chart.defaults.font.family=\"'DM Sans','Segoe UI',system-ui,sans-serif\";")

    return "\n".join(lines)


def update_analytics_page(filepath: str, data: dict) -> bool:
    """
    Update analytics.html with new analytics data.

    Args:
        filepath: Path to analytics.html
        data: Output from analytics.process()

    Returns:
        True if file was updated successfully
    """
    if not os.path.exists(filepath):
        logger.error("Analytics page not found: %s", filepath)
        return False

    html = _read_file(filepath)

    # Replace the script data block
    script_data = generate_analytics_script_data(data)
    html = _replace_script_data(html, script_data)

    # Update last-updated date
    today = date.today()
    try:
        import platform
        if platform.system() == "Windows":
            date_str = today.strftime("%b %#d, %Y")
        else:
            date_str = today.strftime("%b %-d, %Y")
    except ValueError:
        date_str = f"{today.strftime('%b')} {today.day}, {today.year}"

    html = re.sub(
        r'(<div class="updated-date">)[^<]+(</div>)',
        rf'\g<1>{date_str}\2',
        html
    )

    if _validate_html(html):
        _write_file(filepath, html)
        logger.info("Updated %s", filepath)
        return True
    else:
        logger.error("HTML validation failed for %s", filepath)
        return False


# ─── Rep Leaderboard Generator ─────────────────────────────────────────────────

def _generate_scorecard_table(scorecard: list[dict], month_name: str, year: int) -> str:
    """
    Generate the HTML table rows for the rep leaderboard.

    Returns the full inner content between the <!-- Scorecard Data --> markers,
    including the subtitle, table, and data.
    """
    def _fmt_funded(v):
        if v >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        elif v >= 1_000:
            return f"${v/1_000:.1f}K"
        elif v > 0:
            return f"${int(v)}"
        return "$0"

    rows = []
    for i, rep in enumerate(scorecard):
        stops = rep["stops_per_day"]
        enrollments = rep["enrollments"]
        funded = rep["funded"]
        spe = rep.get("stops_per_enroll")  # None if 0 enrollments
        prospect_stops = rep.get("prospect_stops", 0)
        prospect_pct = rep.get("prospect_pct")  # None if 0 total stops

        # Color-code enrollments
        if enrollments >= 10:
            enroll_color = "#2DD4A0"
        elif enrollments >= 5:
            enroll_color = "#FBBF24"
        elif enrollments > 0:
            enroll_color = "#F1F5F9"
        else:
            enroll_color = "#627289"

        # Color-code funded
        if funded >= 5000:
            funded_color = "#2DD4A0"
        elif funded > 0:
            funded_color = "#FBBF24"
        else:
            funded_color = "#627289"

        # Color-code stops
        if stops >= 10:
            stops_color = "#2DD4A0"
        elif stops >= 5:
            stops_color = "#FBBF24"
        elif stops > 0:
            stops_color = "#F1F5F9"
        else:
            stops_color = "#627289"

        # Color-code stops/enrollment ratio (lower = better)
        if spe is None:
            spe_display = "—"
            spe_sub = ""
            spe_color = "#627289"
        elif spe <= 3:
            spe_display = str(spe)
            spe_sub = f'<div style="font-size:0.7em;color:#627289;margin-top:1px">{prospect_stops} visits</div>'
            spe_color = "#2DD4A0"
        elif spe <= 8:
            spe_display = str(spe)
            spe_sub = f'<div style="font-size:0.7em;color:#627289;margin-top:1px">{prospect_stops} visits</div>'
            spe_color = "#FBBF24"
        else:
            spe_display = str(spe)
            spe_sub = f'<div style="font-size:0.7em;color:#627289;margin-top:1px">{prospect_stops} visits</div>'
            spe_color = "#F87171"

        # Color-code prospect % (higher = more hunting)
        if prospect_pct is None:
            pct_display = "—"
            pct_color = "#627289"
        elif prospect_pct >= 70:
            pct_display = f"{prospect_pct}%"
            pct_color = "#5B9BFF"  # blue = heavy hunter
        elif prospect_pct >= 40:
            pct_display = f"{prospect_pct}%"
            pct_color = "#A78BFA"  # purple = balanced
        else:
            pct_display = f"{prospect_pct}%"
            pct_color = "#22D3EE"  # cyan = farmer

        stripe = ' class="sc-stripe"' if i % 2 == 1 else ""
        rows.append(
            f'<tr{stripe}>'
            f'<td class="sc-name">{rep["name"]}</td>'
            f'<td class="sc-num" style="color:{stops_color}">{stops}</td>'
            f'<td class="sc-num" style="color:{pct_color}">{pct_display}</td>'
            f'<td class="sc-num" style="color:{enroll_color}">{enrollments}</td>'
            f'<td class="sc-num" style="color:{spe_color}">{spe_display}{spe_sub}</td>'
            f'<td class="sc-num" style="color:{funded_color}">{_fmt_funded(funded)}</td>'
            f'</tr>'
        )

    # Summary stats
    total_enrollments = sum(r["enrollments"] for r in scorecard)
    total_funded = sum(r["funded"] for r in scorecard)
    active_reps = sum(1 for r in scorecard if r["enrollments"] > 0)

    # Avg stops/enrollment across reps who have enrollments
    reps_with_enrollments = [r for r in scorecard if r["enrollments"] > 0]
    if reps_with_enrollments:
        total_prospects = sum(r.get("prospect_stops", 0) for r in reps_with_enrollments)
        total_enroll = sum(r["enrollments"] for r in reps_with_enrollments)
        avg_spe = round(total_prospects / total_enroll, 1) if total_enroll > 0 else 0
    else:
        avg_spe = 0

    # Team-wide prospect % (all reps with any stops)
    reps_with_stops = [r for r in scorecard if r.get("total_stops", 0) > 0]
    if reps_with_stops:
        team_prospect = sum(r.get("prospect_stops", 0) for r in reps_with_stops)
        team_total = sum(r.get("total_stops", 0) for r in reps_with_stops)
        team_prospect_pct = round(team_prospect / team_total * 100) if team_total > 0 else 0
    else:
        team_prospect_pct = 0

    subtitle = (
        f'Field activity &middot; enrollment &middot; revenue pipeline &middot; '
        f'{month_name} {year}'
    )

    table = (
        f'<div class="sc-subtitle">{subtitle}</div>\n'
        f'<div class="sc-summary">'
        f'<span><b style="color:#22D3EE">{active_reps}</b> active reps</span>'
        f'<span><b style="color:#5B9BFF">{total_enrollments}</b> enrollments</span>'
        f'<span><b style="color:#2DD4A0">{_fmt_funded(total_funded)}</b> funded</span>'
        f'<span><b style="color:#FBBF24">{avg_spe}</b> avg stops/enroll</span>'
        f'<span><b style="color:#A78BFA">{team_prospect_pct}%</b> team prospect</span>'
        f'</div>\n'
        f'<div style="overflow-x:auto">\n'
        f'<table class="sc-table">\n'
        f'<thead><tr>'
        f'<th class="sc-th-name">Rep</th>'
        f'<th class="sc-th-num">Stops/Day</th>'
        f'<th class="sc-th-num">Prospect %</th>'
        f'<th class="sc-th-num">Enrollments</th>'
        f'<th class="sc-th-num">Stops/Enroll</th>'
        f'<th class="sc-th-num">Funded (M0)</th>'
        f'</tr></thead>\n'
        f'<tbody>\n'
        + "\n".join(rows) +
        f'\n</tbody>\n'
        f'</table>\n'
        f'</div>'
    )

    return table


def _generate_isr_scorecard_table(isr_scorecard: list[dict]) -> str:
    """
    Generate the HTML table for the ISR leaderboard (Genesys talk time).

    Returns the full inner content between the <!-- ISR Scorecard Data --> markers.
    """
    rows = []
    max_talk = max((r["talk_seconds"] for r in isr_scorecard), default=1) or 1

    for i, rep in enumerate(isr_scorecard):
        talk_display = rep.get("talk_display", "0m")
        talk_seconds = rep.get("talk_seconds", 0)
        calls = rep.get("calls", 0)
        bar_pct = round((talk_seconds / max_talk) * 100) if max_talk > 0 else 0

        # Color-code talk time (monthly thresholds)
        if talk_seconds >= 40 * 3600:  # 40+ hours
            talk_color = "#2DD4A0"
        elif talk_seconds >= 20 * 3600:  # 20+ hours
            talk_color = "#FBBF24"
        elif talk_seconds > 0:
            talk_color = "#F1F5F9"
        else:
            talk_color = "#627289"

        # Color-code calls (monthly thresholds)
        if calls >= 1000:
            calls_color = "#2DD4A0"
        elif calls >= 500:
            calls_color = "#FBBF24"
        elif calls > 0:
            calls_color = "#F1F5F9"
        else:
            calls_color = "#627289"

        # Rank badge
        rank = i + 1
        if rank == 1:
            rank_style = "background:rgba(251,191,36,0.15);color:#FBBF24"
        elif rank == 2:
            rank_style = "background:rgba(148,163,184,0.15);color:#94A3B8"
        elif rank == 3:
            rank_style = "background:rgba(180,120,80,0.15);color:#CD7F32"
        else:
            rank_style = "background:rgba(98,114,137,0.1);color:#627289"

        stripe = ' class="sc-stripe"' if i % 2 == 1 else ""
        rows.append(
            f'<tr{stripe}>'
            f'<td class="sc-num" style="width:36px"><span style="display:inline-flex;align-items:center;'
            f'justify-content:center;width:24px;height:24px;border-radius:6px;font-size:0.75rem;'
            f'font-weight:700;{rank_style}">{rank}</span></td>'
            f'<td class="sc-name">{rep["name"]}</td>'
            f'<td class="sc-num" style="color:{talk_color}">{talk_display}</td>'
            f'<td class="sc-num" style="color:{calls_color}">{calls}</td>'
            f'<td class="sc-num" style="width:140px;padding-right:16px">'
            f'<div style="height:6px;border-radius:3px;background:rgba(34,211,238,0.15)">'
            f'<div style="height:100%;border-radius:3px;width:{bar_pct}%;'
            f'background:linear-gradient(90deg,#22D3EE,#5B9BFF)"></div></div></td>'
            f'</tr>'
        )

    # Summary stats
    total_talk = sum(r["talk_seconds"] for r in isr_scorecard)
    total_calls = sum(r.get("calls", 0) for r in isr_scorecard)
    active_reps = sum(1 for r in isr_scorecard if r["talk_seconds"] > 0)
    avg_talk = total_talk // active_reps if active_reps > 0 else 0

    total_h = total_talk // 3600
    total_m = (total_talk % 3600) // 60
    avg_h = avg_talk // 3600
    avg_m = (avg_talk % 3600) // 60

    total_display = f"{total_h}h {total_m}m" if total_h > 0 else f"{total_m}m"
    avg_display = f"{avg_h}h {avg_m}m" if avg_h > 0 else f"{avg_m}m"

    subtitle = 'Genesys Cloud &middot; voice calls &middot; current month'

    table = (
        f'<div class="sc-subtitle">{subtitle}</div>\n'
        f'<div class="sc-summary">'
        f'<span><b style="color:#22D3EE">{active_reps}</b> active reps</span>'
        f'<span><b style="color:#5B9BFF">{total_display}</b> total talk</span>'
        f'<span><b style="color:#2DD4A0">{avg_display}</b> avg per rep</span>'
        f'<span><b style="color:#FBBF24">{total_calls:,}</b> calls</span>'
        f'</div>\n'
        f'<div style="overflow-x:auto">\n'
        f'<table class="sc-table">\n'
        f'<thead><tr>'
        f'<th class="sc-th-num" style="width:36px">#</th>'
        f'<th class="sc-th-name">Rep</th>'
        f'<th class="sc-th-num">Talk Time</th>'
        f'<th class="sc-th-num">Calls</th>'
        f'<th class="sc-th-num" style="width:140px">Distribution</th>'
        f'</tr></thead>\n'
        f'<tbody>\n'
        + "\n".join(rows) +
        f'\n</tbody>\n'
        f'</table>\n'
        f'</div>'
    )

    return table


def _replace_between_markers(html: str, marker_name: str, content: str) -> str:
    """
    Replace content between <!-- marker_name --> and <!-- /marker_name --> markers.
    """
    pattern = re.compile(
        rf'(<!--\s*{re.escape(marker_name)}\s*-->)'
        rf'.*?'
        rf'(<!--\s*/{re.escape(marker_name)}\s*-->)',
        re.DOTALL
    )
    replacement = rf'\1\n{content}\n\2'
    new_html, count = pattern.subn(replacement, html)
    if count == 0:
        logger.warning("Markers <!-- %s --> not found in HTML", marker_name)
    return new_html


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
