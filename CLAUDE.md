# EasyPay Finance - OSR Dashboard Hub

## What This Is

A static HTML dashboard hub for EasyPay Finance's outside sales team (OSR) performance tracking. Deployed on Netlify via GitHub. No build step, no framework, no dependencies beyond Chart.js (loaded from CDN). Every page is a self-contained HTML file with inline CSS and JS.

The primary user is Kevin (Sales Program Manager). The dashboards track merchant enrollment, production (funded volume), commission compliance, quarterly targets, and field activity for ~12 outside sales reps.

## File Structure

```
index.html              - Landing page / dashboard hub (with force-update button)
jan-2026.html           - January 2026 monthly dashboard (baseline, manual)
feb-2026.html           - February 2026 monthly dashboard (manual)
mar-2026.html           - March 2026 monthly dashboard (automated)
cohort-tracking.html    - Cohort commission tracker (tabbed: active + baseline)
q1-enrollment.html      - Q1 2026 enrollment compliance tracker
field-activity.html     - Weekly field check-in tracker (Maps data)
automation/             - Salesforce API automation pipeline (Python)
.github/workflows/      - GitHub Actions cron workflow (hourly, weekdays)
netlify/functions/      - Netlify Function for manual force-update trigger
data/snapshots/         - Raw Salesforce JSON archives per month
requirements.txt        - Python dependencies (requests)
CLAUDE.md               - This file
```

## Architecture

Static HTML. Each page embeds its data directly in `<script>` tags as JS variables. No external API calls, no database, no server. Data is processed from Salesforce report exports (Excel) and baked into the HTML at build time.

Styling: Dark theme (#0B0F1A background), DM Sans font, consistent color system across all pages:
- Blue #3B82F6 (enrollments, primary)
- Green #10B981 (funded/producing/positive)
- Amber #F59E0B (targets, warnings, commission)
- Purple #8B5CF6 (conversion, quarterly)
- Cyan #06B6D4 (field activity)
- Red #EF4444 (behind/at risk)

Charts: Chart.js 4.x loaded from CDN. Used on monthly dashboards for bar charts, doughnut charts, and daily trend lines.

## Monthly Dashboard Pattern (jan-2026.html, feb-2026.html, mar-2026.html)

Each monthly dashboard has 4 tabs: Overview, Rep Performance, Markets, Production.

**Data sources (4 Salesforce reports per month):**
1. `New_Enrollments_by_Month` - All company enrollments (total count, states, industries)
2. `Credited_Sales_Team_Enrollments` - OSR-credited subset (per-rep counts, merchant details, locations)
3. `Current_Month_Enrollment_Activity_Report` - Month 0 funding (enrollees' activity in their enrollment month)
4. `Last_Month_Enrollment_Activity_Report` - Multi-month funding (enrollees' activity across subsequent months)

**Features:**
- 5 KPIs (total enrollments, OSR credited, funded volume, funded apps, conversion rate)
- Daily enrollment pace chart
- OSR/All toggle that switches between credited-only and all-channel views
- Product mix doughnut (Lease-to-Own vs Retail Contract)
- Top 5 markets bar chart
- ISR assignment distribution
- Clickable rep scorecards → modal with merchant-level detail
- Full rep bar chart with click-to-modal
- Top 15 producers table
- Production funnel visualization
- Key observations section

**New monthly dashboards are created automatically** by the automation pipeline when a new month starts. The pipeline duplicates the previous month's HTML as a template and injects fresh data. No manual file creation needed.

## Commission Tracking (cohort-tracking.html)

Tracks OSR compliance with Paul Funchess's commission structure:

**Rules:**
- Each monthly enrollment cohort must generate $15,000 in funded volume by end of Month 1
- Month 0 = enrollment month, Month 1 = first full calendar month after enrollment
- Funding from BOTH Month 0 and Month 1 counts toward the $15K target
- If an OSR misses $15K by end of Month 1, they get a Month 2 true-up: hit $30K cumulative by end of Month 2
- Only OSR-credited merchants count (non-credited enrollments excluded)

**Structure:**
- Data-driven tabbed interface: `cohortConfig` array defines all tabs dynamically
- Active cohort (orange tab): the current month's enrollees being tracked
- Baseline/completed cohorts (gray dimmed tab): finalized or pre-structure cohorts
- Each tab shows: KPIs, progress bars per OSR, expandable merchant drilldowns with per-month funding columns

**Current cohorts:**
- Feb → Mar (Active): Feb enrollees, $15K deadline end of March, M2 true-up end of April
- Jan → Feb (Baseline): Pre-commission-structure, retroactive tracking for comparison

**New cohort tabs are created automatically** by the pipeline when a new month starts. The `cohortConfig` array and cohort data variables are injected dynamically.

## Q1 Enrollment Compliance (q1-enrollment.html)

Tracks per-OSR quarterly enrollment targets:

**Rules:**
- 30 enrollments per quarter per OSR
- No single month below 10 (floor)
- Quarterly true-up: if any month falls below 10 but quarter total hits 30, no penalty
- Resets at start of each quarter

**Structure:**
- Data-driven: `quarterConfig` defines quarter number, year, and month keys/labels
- `q1Data` array contains per-OSR enrollment counts by month
- New quarterly pages are created automatically when a new quarter starts

**Current:** Q1 2026 = Jan + Feb + Mar.

## Field Activity Tracker (field-activity.html)

Weekly check-in data from Salesforce Maps.

**Data source:** Maps_Check_Ins_This_Week report (Report 5)

**Features:**
- Leaderboard sorted by total stops
- Day filter (Mon/Tue/Wed) and type filter (Existing/Prospect)
- Existing/Prospect split bar per rep
- Daily bar chart per rep
- Expandable stop list with full comments
- Deduplication logic (some reps log multiple entries per stop, keeps longest comment)

**Existing merchant** = has Branch ID (in Salesforce as Account)
**Prospect** = no Branch ID (Lead object, not yet enrolled)

## Landing Page (index.html)

**Sections:**
1. YTD Summary bar (total enrollments, OSR credited, funded volume, months tracked)
2. Commission Tracking (cohort production card + quarterly enrollment compliance card)
3. Field Activity (weekly check-ins card)
4. Monthly Dashboards (cards per month, auto-collapses after 3 most recent)

**Force-update button:** The "Refresh All Reports" button calls a Netlify Function (`/.netlify/functions/trigger-update`) that triggers the GitHub Actions workflow via API. Requires `GH_PAT` environment variable in Netlify.

**All values are updated automatically** by the pipeline — YTD summary, month cards, commission card, Q1 card, and field activity card.

## Data Flow

**Automated (active, hands-free):**
1. GitHub Actions runs hourly (5 AM – 6 PM PST, weekdays) via `.github/workflows/update-dashboards.yml`
2. Python script authenticates to Salesforce via Connected App (OAuth 2.0 Client Credentials)
3. Pulls 5 core reports via Salesforce Analytics REST API (v62.0)
4. Normalization step converts raw Salesforce data (IDs, null placeholders) to display values
5. Processors transform normalized data → JS data variables matching each page's schema
6. HTML generator injects new data into existing HTML files (script data block + hardcoded KPIs)
7. If a new month/quarter starts, new pages are auto-created from templates
8. Git commit → Netlify auto-deploys
9. Raw report JSON saved to `data/snapshots/{YYYY-MM}/` for historical reference

**Manual force-update:**
1. Kevin clicks "Refresh All Reports" button on index.html
2. Netlify Function triggers GitHub Actions workflow via API
3. Same pipeline runs as above

**Manual fallback (for historical months without snapshots):**
1. Kevin exports Salesforce reports as Excel
2. Claude processes Excel → generates HTML with embedded data
3. Push to GitHub → Netlify deploys

## Automation Architecture

```
automation/
  config.py                  # Report IDs, OSR roster, colors, SF column labels
  salesforce_auth.py         # OAuth 2.0 Client Credentials → SalesforceClient
  salesforce_reports.py      # Fetch + parse reports via Analytics REST API
  processors/
    monthly_dashboard.py     # Reports 1-4 → repCredits, marketData, topProducers, etc.
    cohort_tracking.py       # Reports 2+4 (date overrides) → cohort arrays
    q1_enrollment.py         # Report 2 (per month) → q1Data array
    field_activity.py        # Report 5 → repActivity, repStops, days, dayLabels
    index_page.py            # Aggregates all processors → index.html KPIs
  html_generator.py          # Injects data into HTML (script block split + regex KPIs)
  main.py                    # Orchestrator: auth → fetch → normalize → process → generate
```

**Run locally:** `python -m automation.main --dry-run` (outputs to `output/` dir)
**Run in CI:** Triggered by cron schedule, manual `workflow_dispatch`, or Netlify Function

### Salesforce Report Formats

The Analytics REST API returns reports in different formats depending on report type. The automation handles all three:

- **SUMMARY** format (Reports 1, 2): Stores raw Salesforce IDs in main keys and display labels in `_label_` prefixed keys. E.g., `{"OSR Enrollment Credit": "-", "_label_OSR": "Joseph Guerra", "Account Name": "001TO00...", "_label_Account Name": "Merchant Name", "ISR": "005TO000...", "_label_ISR": "Javier Gonzalez"}`. The normalization step in `main.py` (`_normalize_enrollment_rows()`) converts these to display values.

- **MATRIX** format (Reports 3, 4): Date-prefixed aggregate columns like `"3/1/2026_Sum of Funded Dollars"`. The `_normalize_matrix_to_monthly()` helper splits these into per-month flat rows with standard column names.

- **TABULAR** format (Report 5): Straightforward key-value rows, no special handling needed.

### Data Normalization (main.py)

The `_normalize_enrollment_rows()` function fixes three fields after fetching:
1. **OSR name**: Resolves from `_label_OSR` (authoritative) → `_label_OSR Enrollment Credit` → `Referral/Promo Code` (free-text fallback). Important: `_label_OSR` must be checked before `Referral/Promo Code` because the free-text field may contain abbreviations.
2. **Merchant name**: Resolves from `_label_Account Name` (replaces raw Salesforce Account ID).
3. **ISR name**: Resolves from `_label_ISR` (replaces raw Salesforce User ID).

### Cohort Data Pipeline

For the active cohort (previous month's enrollees):
1. Activity data loaded from Report 4 (matrix format) and normalized via `_normalize_matrix_to_monthly()`
2. Enrollment list loaded from: saved snapshot → API fetch with date override + `reportBooleanFilter` → HTML fallback
3. The `reportBooleanFilter` (e.g., `"1 AND 2 AND 3 AND (4 OR 5 OR 6)"`) is required because Report 2's saved filters use OR logic for conversion fields, but POST filter overrides default to AND logic

### Q1 Data Pipeline

For each month in the quarter:
1. Current month: uses core `credited_enrollments` report
2. Previous months: loaded from snapshot → API fetch via `_fetch_credited_for_month()` → HTML fallback
3. All data normalized before processing

## GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `SF_LOGIN_URL` | Salesforce login URL (e.g., `https://login.salesforce.com`) |
| `SF_CLIENT_ID` | Connected App Consumer Key |
| `SF_CLIENT_SECRET` | Connected App Consumer Secret |

Report IDs are configured in `automation/config.py` (REPORT_IDS dict). Each ID is the 18-character Salesforce Report ID found in the report URL.

## Netlify Environment Variables

| Variable | Description |
|----------|-------------|
| `GH_PAT` | GitHub Personal Access Token (for triggering workflow via API) |

## Salesforce Reports Needed

| # | Report Name | Key Filters | Purpose |
|---|-------------|-------------|---------|
| 1 | New_Enrollments_by_Month | Enrollment Date = THIS MONTH, Record Type = Branch | Total company enrollments |
| 2 | Credited_Sales_Team_Enrollments | Enrollment Date = THIS MONTH, Record Type = Branch, OSR Enrollment Credit != blank | OSR-credited enrollments |
| 3 | Current_Month_Enrollment_Activity_Report | Enrollment Date = THIS MONTH, Record Type = Branch | Month 0 funding |
| 4 | Last_Month_Enrollment_Activity_Report | Enrollment Date = LAST MONTH, Record Type = Branch | Month 1 funding (multi-month columns) |
| 5 | Maps_Check_Ins_This_Week | Date = THIS WEEK | Field check-in activity |

For historical cohorts or Month 2 true-up data, Report 2 and 4 templates are called with filter overrides (including `reportBooleanFilter` for OR logic) to specify the exact enrollment date range needed.

## OSR Roster (as of March 2026)

Claudia Gerhardt, DeLon Phoenix, Eric Henderson, Jared Midkiff, Joseph Guerra, Matthew MacDonald, Omar Corona, Phillip Mason, Sara Porter, Stephanie Whitlock, Yemaira Hernandez, Outside Sales Manager (overflow/unassigned)

## Key Terminology

- **Branch ID**: Unique Salesforce identifier for each merchant account
- **OSR Enrollment Credit**: The rep who gets credit for enrolling a merchant (may differ from the rep who submitted the enrollment)
- **Month 0 / M0**: The month a merchant was enrolled
- **Month 1 / M1**: First full calendar month after enrollment (the $15K deadline)
- **Month 2 / M2**: Second full calendar month after enrollment ($30K true-up window)
- **Cohort**: All merchants enrolled in a specific month, grouped by credited OSR
- **Funded Dollars**: Dollar amount of financed transactions processed through EasyPay
- **Funded Applications**: Number of customer financing applications that resulted in funded transactions
- **Conversion Rate**: Funded Applications / Total Applications
- **ISR**: Inside Sales Rep (supports OSRs, not tracked for commission)

## Color Conventions for Tags

- Green "Latest" / "Live" = active, current data
- Orange "Active" = commission tracking in progress
- Purple "New" = recently added feature
- Gray "Baseline" = pre-commission-structure reference data
- Gray dashed border = placeholder / coming soon

## Common Maintenance Tasks

Most tasks are now handled automatically by the pipeline. Manual intervention is only needed for:

**Roster changes:**
1. Update `OSR_ROSTER` and `OSR_COLORS` in `automation/config.py`
2. Update the roster section in this file

**Report changes:**
1. Update `REPORT_IDS` in `automation/config.py` with new 18-character Salesforce Report IDs
2. If column names change, update `COLUMN_LABELS` in `automation/config.py`

**End of quarter (automated):**
- New quarterly enrollment page is auto-created when a new quarter starts
- Previous quarter page is preserved as an archive
- Index.html is updated automatically

**Debugging the pipeline:**
1. Check GitHub Actions logs for errors
2. Run locally with `python -m automation.main --dry-run` to test
3. Check `data/snapshots/{YYYY-MM}/` for raw API data
4. Common issues:
   - SUMMARY format: check that `_normalize_enrollment_rows()` handles the field correctly
   - Matrix format: check date-prefixed column names in `_normalize_matrix_to_monthly()`
   - POST filter overrides: ensure `reportBooleanFilter` preserves OR logic from saved report
