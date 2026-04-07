# EasyPay Finance - OSR Dashboard Hub

## What This Is

A static HTML dashboard hub for EasyPay Finance's outside sales team (TSR — Territory Sales Rep) performance tracking. Deployed on Netlify via GitHub. No build step, no framework, no dependencies beyond Chart.js (loaded from CDN). Every page is a self-contained HTML file with inline CSS and JS.

The primary user is Kevin (Sales Program Manager). The dashboards track merchant enrollment, production (funded volume), commission compliance, quarterly targets, field activity, ISR phone performance, and territory budget forecasting for the outside sales team.

## File Structure

```
index.html              - Landing page / dashboard hub (scorecard, forecast, force-update)
analytics.html          - Analytics & insights page (admin-only, password-gated)
auth.js                 - Client-side password gate (site-wide + analytics-only)
jan-2026.html           - January 2026 monthly dashboard (baseline, manual)
feb-2026.html           - February 2026 monthly dashboard (manual)
mar-2026.html           - March 2026 monthly dashboard (automated)
apr-2026.html           - April 2026 monthly dashboard (automated)
cohort-tracking.html    - Cohort commission tracker (tabbed: active + baseline)
q1-enrollment.html      - Q1 2026 enrollment compliance tracker (archived)
q2-enrollment.html      - Q2 2026 enrollment compliance tracker (active)
field-activity.html     - Monthly field check-in tracker (Maps data)
territory-review.html   - Territory cohort review page (admin-only, analytics-gated)
genesys-test.html       - Genesys Cloud API test page (ISR talk time)
automation/             - Salesforce + Genesys API automation pipeline (Python)
.github/workflows/      - GitHub Actions cron workflow (hourly, weekdays)
netlify/functions/      - Netlify Function for manual force-update trigger
data/snapshots/         - Raw Salesforce/Genesys JSON archives per month
quarterly-reviews/      - Territory review PPTX decks + build script + data JSON
requirements.txt        - Python dependencies (requests)
CLAUDE.md               - This file
```

## Architecture

Static HTML. Each page embeds its data directly in `<script>` tags as JS variables. No external API calls from the browser, no database, no server. Data is processed from Salesforce and Genesys Cloud APIs and baked into the HTML at build time by the pipeline.

### Color Palette (Lifted Dark Theme)

- Page bg: #0D1321 | Card bg: #151E2F | Borders: #293852
- Text: primary #F1F5F9, secondary #8494AB, tertiary #627289
- Accents: blue #5B9BFF, green #2DD4A0, amber #FBBF24, purple #A78BFA, cyan #22D3EE, red #F87171

Charts: Chart.js 4.x loaded from CDN. Used on monthly dashboards for bar charts, doughnut charts, and daily trend lines.

### Password Protection (auth.js)

Two-tier client-side JS password gate using SHA-256 hashing via Web Crypto API:
- **Site-wide password** ("easypay2026"): gates ALL pages. Stored in localStorage as SHA-256 hash.
- **Analytics-only password** ("adminaccess"): additional gate on analytics.html AND territory-review.html for Kevin/leadership only.
- Full-screen dark overlay (#0D1321) with password prompt. On correct entry, stores hash in localStorage and removes overlay.
- Detection: checks URL pathname for `/analytics` or `/territory-review` (with or without `.html` for Netlify clean URLs).
- All pages include `<script src="auth.js"></script>`. Pipeline-created pages inherit the tag from templates.

## Landing Page (index.html)

**Sections:**
1. YTD Summary bar (total enrollments, OSR credited, funded volume, months tracked)
2. **TSR Leaderboard** — toggle between OSR scorecard, ISR scorecard, Grid view, and Chart view
3. **Production Forecast** — territory budget attainment (% only, no dollar amounts visible to reps)
4. Commission Tracking (cohort production card + quarterly enrollment compliance card)
5. Field Activity (monthly check-ins card)
6. Analytics & Insights (links to analytics.html and territory-review.html)
7. Monthly Dashboards (cards per month, auto-collapses after 3 most recent)

**Force-update button:** "Refresh All Reports" calls Netlify Function → triggers GitHub Actions workflow. Shows last refresh timestamp (injected by pipeline).

**All values are updated automatically** by the pipeline — YTD summary, scorecards, forecast, month cards, commission card, Q1 card, and field activity card.

**YTD Funded Volume:** Shows cumulative funded from ALL cohorts (M0+M1+M2 across all months), not just M0. Extracted from cohort-tracking.html JS data.

### TSR Leaderboard (Scorecard Section)

**Toggle hierarchy:** TSR label with OSR / ISR sub-toggles, plus Grid / Charts view toggle.

**OSR Grid View columns:**
- Rep | Stops/Day | Avg Hrs | Prospect % | Enrollments | Conversion | Funded (M0)

**Key metrics:**
- **Stops/Day**: Total stops ÷ active days
- **Avg Hours in Field**: Time span between first and last check-in per day, averaged across active days. Days with only 1 stop excluded.
- **Prospect %**: Prospect stops ÷ total stops. Blue ≥70% (hunter), Purple 40-69% (balanced), Cyan <40% (farmer).
- **Conversion Rate**: Enrollments ÷ Prospect Stops × 100 (higher = better). Green ≥15%, Amber ≥8%, Red <8%.
- **Funded (M0)**: Sum of funded dollars for merchants the OSR enrolled this month.

**OSR Chart View:** 5 horizontal bar charts ranked by rep — Stops/Day, Avg Hours in Field, Enrollments, Conversion Rate, % Budget Attainment.

**ISR Grid View columns:** # | Rep | Talk Time | Calls | Distribution
- Data sourced from Genesys Cloud API (monthly cumulative, refreshes hourly)

**Summary bars** show team-level aggregates for each view.

### Production Forecast

Displays territory-level budget attainment per OSR. **Public view (index.html) does NOT show dollar amounts** — only percentages (attainment, projected, variance) and pace bars. Full dollar view with MTD actuals and budget targets is on the analytics page (admin-only).

**Columns (public):** Rep | % Attainment | Projected | Variance | Pace
**Columns (analytics):** Rep | MTD Actual | Budget | % Attainment | Projected | Variance | Pace

**Data source:** Report 6 (Monthly Quota) from Salesforce — provides both budget targets and live MTD actuals per user. Falls back to static `forecast_data.py` if report unavailable.

**Calculations:**
- % Attainment = MTD Actual ÷ Budget × 100
- Projected = Uses Salesforce's `Funding Projected` field directly (for consistency with finance team)
- Variance = Projected ÷ Budget × 100 − 100%
- Business days = weekdays only (Mon–Fri)

**Color coding for attainment:** Green if on pace (attainment ≥ expected %), Amber within 80% of expected pace, Red if behind.

**Early month banner:** Shows blue info banner on business days 1-3: "Early month — projections stabilizing"

### Cohort Production Card

The cohort card on index.html dynamically updates its labels each month:
- **Active cohort** (green): previous month's enrollees (e.g., "Mar Cohort" when in April)
- **Current cohort** (blue): this month's enrollees in M0 (e.g., "Apr Cohort")
- Footer text updates automatically (e.g., "Tabbed: Mar (active) + Apr (M0)")

### Quarterly Enrollment Compliance Card

Auto-detects current quarter and updates Q label, targets, and link. When Q2+ is active, shows "Previous: Q1 2026 (Jan – Mar)" archive link below the card.

## Analytics Page (analytics.html)

Admin-only page gated behind the analytics password. Three tabs:

1. **Trends & Insights** — KPI trend cards, enrollment trend chart, daily pace overlay, funded velocity
2. **Rep Analytics** — top improvers/decliners, per-rep mini charts, Q1 compliance forecast, enrollment efficiency
3. **Production & Forecasts** — enrollment-to-funding funnel, cohort health, market trends, product mix, **Territory Budget Forecast (full admin view with MTD $ and budget $)**, month-end projections

The Territory Budget Forecast table is injected by the pipeline between `<!-- Analytics Forecast Data -->` markers.

## Territory Cohort Review (territory-review.html)

Admin-only page gated behind the analytics password. Interactive territory-level cohort analysis.

**Features:**
- Territory selector dropdown (all 12 assigned territories)
- 7 sections: Summary banner, Cohort scorecard, Activity vs Output, ISR Conditioning, Producer Patterns, Gap Detection, Pipeline Categorization
- PDF export via html2pdf.js (client-side, "Generate Report" button)
- Data injected by pipeline as `territoryReviewData` JS variable keyed by territory code

**Data sources:** Reports 1-6 + Report 7 (ISR Notes) + Genesys + field activity
**ISR Notes processing:** Groups by Branch ID, computes touches per BID, days to first touch, OB sequence tracking (OB1→OB2→OB3→OB Final), flags 72-hour violations

## Monthly Dashboard Pattern (jan-2026.html through apr-2026.html)

Each monthly dashboard has 4 tabs: Overview, Rep Performance, Markets, Production.

**Data sources (4 Salesforce reports per month):**
1. `New_Enrollments_by_Month` - All company enrollments (total count, states, industries)
2. `Credited_Sales_Team_Enrollments` - OSR-credited subset (per-rep counts, merchant details, locations)
3. `Current_Month_Enrollment_Activity_Report` - Month 0 funding (enrollees' activity in their enrollment month)
4. `Last_Month_Enrollment_Activity_Report` - Multi-month funding (enrollees' activity across subsequent months)

**New monthly dashboards are created automatically** by the automation pipeline when a new month starts.

## Commission Tracking (cohort-tracking.html)

Tracks OSR compliance with Paul Funchess's commission structure:

**Rules:**
- Each monthly enrollment cohort must generate $15,000 in funded volume by end of Month 1
- Month 0 = enrollment month, Month 1 = first full calendar month after enrollment
- Funding from BOTH Month 0 and Month 1 counts toward the $15K target
- If an OSR misses $15K by end of Month 1, they get a Month 2 true-up: hit $30K cumulative by end of Month 2
- Only OSR-credited, **in-territory** merchants count (filtered by OS Territory column matching TERRITORY_MAP)
- Non-roster names (like "-", "friend") are filtered out via OSR_ROSTER check

**New cohort tabs are created automatically** by the pipeline when a new month starts.

## Field Activity Tracker (field-activity.html)

Monthly check-in data from Salesforce Maps (Report 5).

**2,000 row API limit handling:** The pipeline fetches Report 5 in two halves (first half of month + second half) to avoid Salesforce's 2,000 row cap per API call. Results are merged and deduplicated.

## Data Flow

**Automated (active, hands-free):**
1. GitHub Actions runs hourly (5 AM – 6 PM PST, weekdays) via `.github/workflows/update-dashboards.yml`
2. Python script authenticates to Salesforce via Connected App (OAuth 2.0 Client Credentials)
3. Pulls 7 Salesforce reports via Analytics REST API (v62.0)
4. Authenticates to Genesys Cloud via OAuth 2.0 Client Credentials
5. Pulls ISR talk time data via Genesys Analytics API
6. Normalization step converts raw Salesforce data (IDs, null placeholders) to display values
7. Processors transform normalized data → JS data variables matching each page's schema
8. HTML generator injects new data into existing HTML files (script data block + marker-based sections)
9. If a new month/quarter starts, new pages are auto-created from templates
10. Git commit → Netlify auto-deploys
11. Raw report JSON saved to `data/snapshots/{YYYY-MM}/` for historical reference

**Manual force-update:**
1. Kevin clicks "Refresh All Reports" button on index.html
2. Netlify Function triggers GitHub Actions workflow via API
3. Same pipeline runs as above

## Automation Architecture

```
automation/
  config.py                  # Report IDs, OSR/ISR rosters, territory map, colors, SF column labels
  salesforce_auth.py         # OAuth 2.0 Client Credentials → SalesforceClient
  salesforce_reports.py      # Fetch + parse reports via Analytics REST API
  genesys_auth.py            # Genesys Cloud OAuth 2.0 → GenesysClient
  genesys_reports.py         # Fetch ISR talk time via Genesys Analytics API
  forecast_data.py           # Static fallback budget/actuals data (used if Report 6 unavailable)
  test_genesys.py            # Standalone Genesys API test script
  processors/
    monthly_dashboard.py     # Reports 1-4 → repCredits, marketData, topProducers, etc.
    cohort_tracking.py       # Reports 2+4 (date overrides) → cohort arrays (territory-filtered)
    q1_enrollment.py         # Report 2 (per month) → q1Data array
    field_activity.py        # Report 5 → repActivity, repStops, days, dayLabels, avg_hours
    forecast.py              # Report 6 (or fallback) → territory budget forecast per OSR
    territory_review.py      # Reports 1-7 + Genesys → per-territory cohort review (7 sections)
    analytics.py             # Multi-month trends → analytics.html data
    index_page.py            # Aggregates all processors → index.html KPIs + scorecards
  html_generator.py          # Injects data into HTML (script block + marker sections + regex KPIs)
  main.py                    # Orchestrator: auth → fetch → normalize → process → generate
```

**Run locally:** `py -m automation.main --dry-run` (outputs to `output/` dir)
**Run in CI:** Triggered by cron schedule, manual `workflow_dispatch`, or Netlify Function

### Salesforce Report Formats

- **SUMMARY** format (Reports 1, 2): Stores raw Salesforce IDs in main keys and display labels in `_label_` prefixed keys.
- **MATRIX** format (Reports 3, 4): Date-prefixed aggregate columns like `"3/1/2026_Sum of Funded Dollars"`.
- **TABULAR** format (Reports 5, 6, 7): Straightforward key-value rows. Report 6 has currency fields as `{amount, currency}` dicts. Report 7 (ISR Notes) fetched with date-split pattern like Report 5.

### Report 6 (Monthly Quota) Special Handling

Report 6 uses `_label_User` for rep names. Currency fields come as `{amount: float, currency: null}` dicts. The `Funding Projected` field from Salesforce is used directly for projections (not our own calculation) for consistency with the finance team.

### Report 7 (ISR Notes) Split Fetch

Report 7 has 10,000+ rows per quarter. Fetched per-month within the current quarter using the same split-date pattern as Report 5. Results merged and deduplicated by (Branch ID, ISR, Subject, Created Date).

### Maps Check-In Split Fetch

Report 5 (Maps Check-Ins) is fetched in two API calls to avoid Salesforce's 2,000 row limit. Split point calculated automatically.

### Data Normalization (main.py)

The `_normalize_enrollment_rows()` function fixes three fields after fetching:
1. **OSR name**: Resolves from `_label_OSR` (authoritative) → `_label_OSR Enrollment Credit` → `Referral/Promo Code` (free-text fallback).
2. **Merchant name**: Resolves from `_label_Account Name` (replaces raw Salesforce Account ID).
3. **ISR name**: Resolves from `_label_ISR` (replaces raw Salesforce User ID).

### Cohort Territory Filtering

The cohort processor (`cohort_tracking.py`) filters merchants by the `OS Territory` column (uses `_label_OS Territory` for display codes like "LTO-7"). Only merchants in the OSR's assigned territory (per `TERRITORY_MAP`) count toward $15K/$30K targets. The `-` value is treated as blank (no filter). Enrollment credit still counts on the scorecard regardless of territory.

### Historical Month Snapshot Handling

The pipeline only processes the current month's data live. For past months on the index page (month cards, YTD summary), it uses:
1. `_load_month_snapshot_all()` — requires BOTH `new_enrollments.json` AND `credited_enrollments.json` in the snapshot directory
2. If incomplete → falls back to `_extract_monthly_from_html()` which reads KPIs from the existing dashboard HTML
3. Past month dashboard HTML files are NEVER reprocessed by the pipeline — they stay frozen

The `_refresh_past_month_snapshot()` helper exists for one-time re-fetches of credited enrollment data (e.g., when SF credits are corrected after month closes). It updates ONLY the snapshot JSON, NOT the dashboard HTML.

### HTML Injection Patterns

The pipeline uses two injection methods:
1. **Script data block replacement**: Replaces content between `<script>` tag and first `function` keyword.
2. **Marker-based replacement**: Replaces content between `<!-- Marker Name -->` and `<!-- /Marker Name -->` comment pairs:
   - `<!-- Scorecard Data -->` — TSR leaderboard on index.html
   - `<!-- ISR Scorecard Data -->` — ISR leaderboard on index.html
   - `<!-- Forecast Data -->` — Production forecast on index.html
   - `<!-- Analytics Forecast Data -->` — Full budget forecast on analytics.html
   - `<!-- Pipeline Timestamp -->` — Last refresh timestamp on index.html

## GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `SF_LOGIN_URL` | Salesforce login URL (e.g., `https://login.salesforce.com`) |
| `SF_CLIENT_ID` | Connected App Consumer Key |
| `SF_CLIENT_SECRET` | Connected App Consumer Secret |
| `GENESYS_CLIENT_ID` | Genesys Cloud OAuth Client ID |
| `GENESYS_CLIENT_SECRET` | Genesys Cloud OAuth Client Secret |
| `GENESYS_REGION` | Genesys Cloud domain (e.g., `usw2.pure.cloud`) |

Report IDs are configured in `automation/config.py` (REPORT_IDS dict).

## Netlify Environment Variables

| Variable | Description |
|----------|-------------|
| `GH_PAT` | GitHub Personal Access Token (for triggering workflow via API) |

## Salesforce Reports

| # | Report Name | Format | Key Filters | Purpose |
|---|-------------|--------|-------------|---------|
| 1 | New_Enrollments_by_Month | SUMMARY | Enrollment Date = THIS MONTH, Record Type = Branch | Total company enrollments |
| 2 | Credited_Sales_Team_Enrollments | SUMMARY | Enrollment Date = THIS MONTH, Record Type = Branch, OSR Credit != blank | OSR-credited enrollments |
| 3 | Current_Month_Enrollment_Activity | MATRIX | Enrollment Date = THIS MONTH, Record Type = Branch | Month 0 funding |
| 4 | Last_Month_Enrollment_Activity | MATRIX | Enrollment Date = LAST MONTH, Record Type = Branch | Month 1+ funding |
| 5 | Maps_Check_Ins | TABULAR | Created Date = THIS MONTH | Field check-in activity (fetched in 2 halves) |
| 6 | Monthly_Quota | TABULAR | First Date of Month = THIS MONTH | Territory budget targets + MTD funded actuals |
| 7 | ISR_Notes_Touch_Points | TABULAR | Created Date = current quarter | ISR conditioning activity (fetched per-month with split) |

For historical cohorts or Month 2 true-up data, Report 2 and 4 templates are called with filter overrides (including `reportBooleanFilter` for OR logic).

**Important:** `_fetch_credited_for_month()` does NOT use conversion flag filters — it fetches ALL credited enrollments for the month (Record Type = Branch + date range only). This ensures unconverted enrollments are included for cohort tracking.

## Genesys Cloud API

- **Auth**: OAuth 2.0 Client Credentials → `https://login.{region}/oauth/token`
- **API**: `https://api.{region}/api/v2/analytics/conversations/aggregates/query`
- **Data**: Monthly cumulative talk time and call counts per agent
- **Interval**: 1st of current month → now (recalculated each hourly run)
- **Metrics**: `tTalkComplete` (talk seconds), `nConnected` (call count)
- **Roster filtering**: Only ISR_ROSTER names are shown on the dashboard

## OSR Roster (as of April 2026)

Cesar Flores, Claudia Gerhardt, DeLon Phoenix, Eric Henderson, Jared Midkiff, Jeremy Moore, Joseph Guerra, Matthew MacDonald, Omar Corona, Phillip Mason, Stephanie Whitlock, Yemaira Hernandez, Outside Sales Manager (overflow/unassigned)

## ISR Roster (as of April 2026)

Connor Admirand, Javier Gonzalez, Katie Anguiano, Laura Angulo, Michael Palmer, Noemy Carrion

## ISR → Territory Assignments

| ISR | Territories |
|-----|-------------|
| Javier Gonzalez | LTO-1 (Yemaira), LTO-5 (Jared) |
| Noemy Carrion | LTO-2 (Omar), LTO-3 (Joseph) |
| Connor Admirand | LTO-7 (Stephanie), RIC-8 (Eric) |
| Katie Anguiano | RIC-1 (Cesar), RIC-2 (Claudia), RIC-4 (Jeremy) |
| Laura Angulo | RIC-6 (Phillip) |
| Michael Palmer | RIC-7 (DeLon), RIC-9 (Matthew) |

## Territory → OSR Mapping

| Territory | OSR | State/Area |
|-----------|-----|------------|
| LTO-1 | Yemaira Hernandez | FL (Miami-Dade/Broward) |
| LTO-2 | Omar Corona | TX (S. Houston/Valley/El Paso) |
| LTO-3 | Joseph Guerra | TX (State Manager) |
| LTO-5 | Jared Midkiff | FL (State Manager) |
| LTO-7 | Stephanie Whitlock | GA/NE FL/Panhandle |
| RIC-1 | Cesar Flores | CA (LA Metro Core) |
| RIC-2 | Claudia Gerhardt | CA (IE South/San Diego) |
| RIC-4 | Jeremy Moore | CA (Orange County/SE LA) |
| RIC-6 | Phillip Mason | CA (Sacramento/NorCal) |
| RIC-7 | DeLon Phoenix | NV (Las Vegas/Reno) |
| RIC-8 | Eric Henderson | PA (4 Metros) |
| RIC-9 | Matthew MacDonald | AZ (State Manager + NM/UT/ID) |

**Unassigned territories:** LTO-4 (Sara Porter, departed), LTO-8, RIC-3, RIC-5 — hiring in progress.

## Key Terminology

- **TSR**: Territory Sales Rep — umbrella term for OSR and ISR on the dashboard
- **OSR**: Outside Sales Rep (field reps who visit merchants)
- **ISR**: Inside Sales Rep (phone-based, tracked via Genesys)
- **Branch ID / BID**: Unique Salesforce identifier for each merchant account
- **OSR Enrollment Credit**: The rep who gets credit for enrolling a merchant
- **OS Territory**: Salesforce field on merchant records identifying which territory they belong to
- **Month 0 / M0**: The month a merchant was enrolled
- **Month 1 / M1**: First full calendar month after enrollment (the $15K deadline)
- **Month 2 / M2**: Second full calendar month after enrollment ($30K true-up window)
- **Cohort**: All merchants enrolled in a specific month, grouped by credited OSR
- **Funded Dollars**: Dollar amount of financed transactions processed through EasyPay
- **Conversion Rate**: Enrollments ÷ Prospect Stops × 100 (on scorecard); Funded Apps ÷ Total Apps (on monthly dashboards)
- **Attainment**: MTD Funded Dollars ÷ Monthly Budget Target × 100
- **Territory**: Geographic sales area with its own budget target (LTO-x or RIC-x code)
- **OB Sequence**: ISR conditioning steps — OB1 Welcome → OB2 Demo → OB3 Follow-up → OB Final

## Quarterly Territory Review Decks (quarterly-reviews/)

PPTX decks generated per territory for leadership reviews. Built with pptxgenjs via Node.js.

**Files:**
- `q1_data.json` — extracted Q1 data for all territories (enrollment counts, cohort funding, producer lists, ISR touches, field activity, avg days to first touch)
- `build_all_decks.js` — the build script that generates all 10 decks from q1_data.json
- `{TERR}_Q1_Territory_Review.pptx` — 11-slide deck per territory

**11-slide structure:**
1. Title (dark) — territory, OSR/ISR, markets
2. The One-Line Problem (dark) — 3 stat boxes, activity summary, thesis
3. Cohort Scorecard (light) — table with PASS/FAIL by month
4. Activity vs Output (light) — two-column comparison
5. ISR Conditioning (light) — touches per cohort, avg days to first touch, OB reference
6. Where Production Lives (light) — all producing merchants with BIDs
7. ISR Touch Point Summary (dark) — ISR-specific stats and per-cohort breakdown
8. Gaps & Flags (light) — auto-detected issues
9. Q2 Pipeline (light) — HIGH/RETAIN/GROW/ACT NOW categories
10. Flags to Resolve (light) — action items with owners and deadlines
11. Close (dark) — $15K/$30K/100% standards, Q2 outlook

**Key data points per territory:**
- Total enrolled vs in-territory (only in-territory counts for $15K)
- Per-cohort: enrolled, in-territory, producing, M0+M1 funding, avg days to first ISR touch
- All producing merchants with real names, BIDs, funded amounts
- TSR check-ins total + enrolled-shop check-ins
- ISR touches per cohort with assigned ISR name

**To rebuild:** `cd "C:\Claude Work\OSR Enrollment Dash" && node quarterly-reviews/build_all_decks.js`

## Common Maintenance Tasks

**Roster changes:**
1. Update `OSR_ROSTER` (or `ISR_ROSTER`) in `automation/config.py`
2. If the rep has a territory, update `TERRITORY_MAP` in `automation/config.py`
3. Update the roster/territory sections in this file

**Report changes:**
1. Update `REPORT_IDS` in `automation/config.py` with new 18-character Salesforce Report IDs
2. If column names change, update `COLUMN_LABELS` in `automation/config.py`

**Correcting past month data (e.g., SF credits updated after month closed):**
1. Add a one-time `_refresh_past_month_snapshot(client, month, year, output_dir)` call in main.py
2. This re-fetches credited enrollments and updates the snapshot JSON only (NOT the dashboard HTML)
3. Remove the one-time block after it runs successfully

**End of quarter (automated):**
- New quarterly enrollment page is auto-created when a new quarter starts
- Previous quarter page preserved as archive with "Previous: Q1 2026" link
- Index.html is updated automatically

**Debugging the pipeline:**
1. Check GitHub Actions logs for errors
2. Run locally with `py -m automation.main --dry-run` to test
3. Check `data/snapshots/{YYYY-MM}/` for raw API data
4. Common issues:
   - SUMMARY format: check that `_normalize_enrollment_rows()` handles the field correctly
   - Matrix format: check date-prefixed column names in `_normalize_matrix_to_monthly()`
   - POST filter overrides: ensure `reportBooleanFilter` preserves OR logic from saved report
   - Report 6 currency fields: values are `{amount, currency}` dicts, extract `.get("amount", 0)`
   - Maps 2000-row limit: if stops data looks incomplete, check both halves fetched correctly
   - Genesys auth: region must match exactly (e.g., `usw2.pure.cloud`)
   - OS Territory: uses `_label_OS Territory` (not raw field which has SF IDs). Treat `-` as blank.
   - Snapshot completeness: `_load_month_snapshot_all` requires both `new_enrollments.json` AND `credited_enrollments.json` — if either missing, falls back to HTML extraction

## Production

- **URL**: https://monthlyenrollmentdash.netlify.app/
- **Pipeline**: GitHub Actions hourly (5 AM – 6 PM PST weekdays)
- **Force update**: Netlify function at `/.netlify/functions/trigger-update`
- **Python executable on Kevin's machine**: `py` (not `python` or `python3`)
