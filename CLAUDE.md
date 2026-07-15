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
hybrid-activity.html    - Hybrid Role Tracker drill-down (full notes + check-in feed)
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
6. **Hybrid Role Tracker** — per-rep activity card for mixed inside/outside roles (currently Marco Garmendia, RIC-10)
7. Analytics & Insights (links to analytics.html and territory-review.html)
8. Monthly Dashboards (cards per month, auto-collapses after 3 most recent)

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

**ISR Grid View columns:** # | Rep | Talk Time | Calls | OB2 | Distribution
- Data sourced from Genesys Cloud API (monthly cumulative, refreshes hourly)
- **OB2 column** counts unique BIDs per ISR with subjects starting with "OB 2 Demo", "OB2 Demo", "OB 2 Merchant Refused Training", "OB 2 OSR Demo", "LTO Training Call", or "LTO Training". Deduped by BID (not by note count) — so 3 notes on the same merchant = 1 OB2 completion. Counted from Report 7 (ISR Notes) via `_label_ISR` field.

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

### Hybrid Role Tracker

Per-rep monthly activity card for reps in a mixed inside/outside role. Configured via `HYBRID_REPS` in config.py (`{name: territory}` — currently `{"Marco Garmendia": "RIC-10"}`); one card renders per entry, so adding a hybrid rep is a one-line config change.

**Data sources (per rep, current month):**
- **Salesforce notes** — Report 7 (ISR Notes) rows where `_label_Created By` (note author) matches the rep. The report's ISR column is the ACCOUNT's assigned ISR, not the note author, so it can't attribute a hybrid rep's own notes — the Created By column was added to Report 7 (July 2026) specifically for this. Falls back to `_label_ISR` matching only if the Created By column ever disappears from the report. (ISR leaderboard, OB2 counts, and territory reviews still use `_label_ISR`, unchanged.) **Open tasks are excluded**: Report 7 has no task-status column, but open call-back/follow-up reminders always come through with blank Full Comments while logged calls carry text — so notes with no comment are skipped (only completed activity counts).
- **Maps check-ins** — reuses the deduped per-rep stop list from `field_activity.process()` (`repStops`), so counts match the field-activity page exactly.
- **Genesys** — matched by exact name in the Genesys agent data. Shows "Genesys: pending setup" until the rep's name appears (lights up automatically once they're set up in Genesys — no roster change needed since the widget matches by name, not ISR_ROSTER).

**Card contents:** summary chips (notes logged, merchants touched, field check-ins, prospect stops, active days, talk time/calls), a daily notes-vs-check-ins table, and a Top Merchants table (top 8 by notes+check-ins, with BID chip and last-touch date, plus a "+N more" footer). Renders an explanatory empty state when the rep has no activity yet. A "Full activity →" link opens the drill-down page.

**Drill-down page (hybrid-activity.html):** every note and check-in for the month, grouped by day, with full comment text, All/Notes/Field filter pills, and text search. Data injected via the script-data-block pattern (`hybridActivityData` JS var) by `update_hybrid_activity()`.

**Pipeline:** `processors/hybrid_tracker.py` → `index_data["hybrid_tracker"]` (main.py Step 8) → `_generate_hybrid_tracker_html()` → injected between `<!-- Hybrid Tracker Data -->` markers on index.html; same card data (incl. `entries`) also feeds `update_hybrid_activity()` for hybrid-activity.html.

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
- **PDF export** via html2pdf.js (client-side, "PDF Report" button)
- **PPTX deck generation** via pptxgenjs CDN (client-side, no backend):
  - **Quarterly Deck** button: full 11-slide deck matching `quarterly-reviews/build_all_decks.js` design
  - **Generate [Month] Deck** button on each cohort card: 7-slide monthly subset
  - Same styling (dark/light slides, Calibri, stat boxes, alternating table rows)
- Data injected by pipeline as `territoryReviewData` JS variable keyed by territory code
- `fmtDays()` always shows decimal format (e.g., "0.8 days", "1.6 days") — no "<1 day" threshold

**ISR name assignment:** Uses `ISR_TERRITORY_MAP` in config.py as primary source, with ISR Notes frequency as override (so if notes show a different ISR, that name wins).

**Data sources:** Reports 1-6 + Report 7 (ISR Notes) + Genesys + field activity
**ISR Notes processing:** Groups by Branch ID, computes touches per BID, days to first touch, OB sequence tracking (OB1→OB2→OB3→OB Final), flags 72-hour violations. Per-cohort `isr_touches` field included in `isr_conditioning` output for deck generation.

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
- **M2 true-up is OR logic**: only available if the cohort FAILED $15K in M1. If M1 passed, true-up is n/a.
- Only OSR-credited, **in-territory** merchants count (filtered by OS Territory column matching TERRITORY_MAP)
- Non-roster names (like "-", "friend") are filtered out via OSR_ROSTER check

**Credit attribution — SINGLE SOURCE OF TRUTH:**
- The `OSR Enrollment Credit` field in Salesforce is the ONLY source used for commission credit.
- `_label_OSR` (territory owner) is NOT used as a fallback — it's the territory assignment, not the credit.
- If `OSR Enrollment Credit` is blank ("-"), the enrollment is counted as uncredited and excluded from all cohort calculations.
- Once the SF admin assigns credit, the next pipeline run picks it up automatically.

**Rep names show territory code**: e.g., "Stephanie Whitlock (LTO-7)" in cohort tables.

**New cohort tabs are created automatically** by the pipeline when a new month starts.

## Field Activity Tracker (field-activity.html)

Monthly check-in data from Salesforce Maps (Report 5).

**Multi-month toggle:** Page shows pills at the top (e.g., "Mar 2026" / "Apr 2026") to switch between current and previous month's check-in data. Implemented via `monthlyFieldData` JS object injected by the pipeline. Click a month pill to swap `repActivity`, `repStops`, `days`, `dayLabels`, KPIs, and calendar without reloading.

**2,000 row API limit handling:** The pipeline fetches Report 5 in two halves (first half of month + second half) to avoid Salesforce's 2,000 row cap per API call. Results are merged and deduplicated.

## Data Flow

**Automated (active, hands-free):**
1. GitHub Actions runs hourly on weekdays via `.github/workflows/update-dashboards.yml`. Cron fires at **:17 past the hour** (not :00 — top-of-hour runs get dropped/delayed by GitHub's shared-runner congestion). Coverage: ~6 AM–6 PM PT weekdays, plus a month-end late-evening catch-up on days 28–31 (`17 3-6 29-31,1 * *`) to capture late end-of-month funding. See "Pipeline timing & self-healing windows" below.
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
  cohort_emails.py           # Weekly per-rep cohort email — see "Cohort Email Subsystem" below
  test_genesys.py            # Standalone Genesys API test script
  probe_genesys_access.py    # Diagnostic: what can the Genesys OAuth client query (run via workflow)
  pull_merchant_inbound.py   # One-off: Merchant Services inbound call analytics (run via workflow)
  processors/
    monthly_dashboard.py     # Reports 1-4 → repCredits, marketData, topProducers, etc.
    cohort_tracking.py       # Reports 2+4 (date overrides) → cohort arrays (territory-filtered)
    q1_enrollment.py         # Report 2 (per month) → q1Data array
    field_activity.py        # Report 5 → repActivity, repStops, days, dayLabels, avg_hours
    hybrid_tracker.py        # Reports 5+7 + Genesys → Hybrid Role Tracker card (HYBRID_REPS)
    forecast.py              # Report 6 (or fallback) → territory budget forecast per OSR
    territory_review.py      # Reports 1-7 + Genesys → per-territory cohort review (7 sections)
    analytics.py             # Multi-month trends → analytics.html data
    index_page.py            # Aggregates all processors → index.html KPIs + scorecards
  html_generator.py          # Injects data into HTML (script block + marker sections + regex KPIs)
  main.py                    # Orchestrator: auth → fetch → normalize → process → generate
```

**Run locally:** `py -m automation.main --dry-run` (outputs to `output/` dir)
**Run in CI:** Triggered by cron schedule, manual `workflow_dispatch`, or Netlify Function

### Cohort Email Subsystem (`cohort_emails.py`) — standalone, NOT in the main pipeline

Weekly per-rep cohort-status email, separate from the dashboard pipeline (main.py does not import it). Flow:
- Reads cohort data from `cohort-tracking.html` and writes **one JSON envelope per OSR** (`{to, subject, html_body}`) to the OneDrive **outbox** folder (`COHORT_EMAIL_OUTBOX` in config.py, default `…/OSR Reports/Outbox`).
- **Power Automate** watches that outbox and sends each envelope as an Outlook email. Cadence target: Monday 9 AM PT via Windows Task Scheduler (local machine, not GitHub Actions).
- Recipients come from **`OSR_EMAILS`** in config.py — **keys MUST stay in sync with `OSR_ROSTER`** (add/remove reps in both; set value to `""` to skip a rep, e.g. the Outside Sales Manager). This is why the roster-maintenance steps below also touch OSR_EMAILS.
- Run modes: `py -m automation.cohort_emails --test` (one envelope to Kevin w/ sample data), `--from-html` (one per rostered rep), `--from-html --rep "Name"` (single-rep dry run), `--out ./output` (override outbox).

### Diagnostic / one-off workflows (`.github/workflows/`)

Manual (`workflow_dispatch`) only — not scheduled, safe to leave in place:
- **`probe-genesys.yml`** → `probe_genesys_access.py`: reports what the Genesys OAuth client (role `API_Analytics`) can query. Confirmed OK: conversation aggregates + details, user aggregates, users directory, routing queues, queue observations, presence, quality; DENIED: wrap-up codes, WFM, OAuth admin.
- **`pull-merchant-inbound.yml`** → `pull_merchant_inbound.py`: daily inbound call analytics + full per-call log (caller ANI) for queues matching a `queue_filter` input (default "merchant" → "Merchant Services Voice" + "Merchant Service Spanish"). Output uploaded as an artifact (xlsx + CSVs), not committed.

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

The `_normalize_enrollment_rows()` function fixes fields after fetching:
1. **OSR credit**: The SUMMARY grouping field `OSR Enrollment Credit` already contains the display name (or "-" when unassigned). No fallback to `_label_OSR` — that's territory owner, not credit.
2. **Merchant name**: Resolves from `_label_Account Name` (replaces raw Salesforce Account ID).
3. **ISR name**: Resolves from `_label_ISR` (replaces raw Salesforce User ID).

### Cohort Territory Filtering

The cohort processor (`cohort_tracking.py`) filters merchants by the `OS Territory` column (uses `_label_OS Territory` for display codes like "LTO-7"). Only merchants in the OSR's assigned territory (per `TERRITORY_MAP`) count toward $15K/$30K targets. The `-` value is treated as blank (no filter). Enrollment credit still counts on the scorecard regardless of territory.

### Historical Month Snapshot Handling

The pipeline processes the current month's data live. For past months on the index page (month cards, YTD summary), it uses:
1. `_load_month_snapshot_all()` — requires BOTH `new_enrollments.json` AND `credited_enrollments.json` in the snapshot directory
2. If incomplete → falls back to `_extract_monthly_from_html()` which reads KPIs from the existing dashboard HTML

### Pipeline timing & self-healing windows (Step 2b in main.py)

Several time-gated refresh behaviors keep recently-closed data current without manual intervention. A new feature touching main.py should preserve these:

- **Prior-month snapshot refresh (every run):** re-fetches the previous month's credited enrollments (`_refresh_past_month_snapshot`, catches SF credit reassignments) and cohort activity (`fetch_cohort_activity`, catches late-posting funding). Snapshot JSON only.
- **Prior-month monthly_quota refresh (days 1–7 of new month):** re-pulls Report 6 for the just-closed month so budget/attainment settles.
- **Prior-month dashboard HTML regeneration (days 1–5 of new month, the "regen window"):** unlike older months, the *immediately* prior month's `{mon}-{year}.html` IS regenerated during days 1–5 so its headline numbers track late SF credits/funding — but only when both the enrollment and activity refreshes succeeded that run (avoids mixed-vintage data). After day 5 it freezes permanently. Months 2+ back are never regenerated.
- **Older-cohort refresh (offsets 2–3):** each run also re-pulls and re-renders the cohort tracker entries for the cohorts 2 and 3 months back (their M1/M2 windows are still settling). Without this, cohort $ silently drifts from SF as late funding posts. This is why `cohort-tracking.html` shows movement on cohorts older than the active one.
- **Idempotent Feb-2026 quota backfill:** Report 6 collection began in March 2026, so `2026-02/monthly_quota.json` was missing; a guarded block backfills it once (needed for PIP Trigger-A history) and no-ops thereafter. Pattern to copy if another month's snapshot ever needs a one-time backfill.

**Correcting older past-month data manually:** add a one-time `_refresh_past_month_snapshot()` call in main.py, let it run once, then remove it (see Common Maintenance Tasks).

### HTML Injection Patterns

The pipeline uses two injection methods:
1. **Script data block replacement**: Replaces content between `<script>` tag and first `function` keyword.
2. **Marker-based replacement**: Replaces content between `<!-- Marker Name -->` and `<!-- /Marker Name -->` comment pairs:
   - `<!-- Scorecard Data -->` — TSR leaderboard on index.html
   - `<!-- ISR Scorecard Data -->` — ISR leaderboard on index.html
   - `<!-- Forecast Data -->` — Production forecast on index.html
   - `<!-- Hybrid Tracker Data -->` — Hybrid Role Tracker card(s) on index.html
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

## OSR Roster (as of June 2026)

Cesar Flores, Claudia Gerhardt, Eric Henderson, Jared Midkiff, Jose Valencia, Joseph Guerra, Marco Garmendia, Mariana Gross, Matthew MacDonald, Omar Corona, Phillip Mason, Richard Herrera, Stephanie Whitlock, Yemaira Hernandez, Outside Sales Manager (overflow/unassigned)

*Francisco Gonzalez (LTO-4) and DeLon Phoenix (RIC-7) removed June 2026; both territories now unassigned. Frozen past-month dashboards still show them historically.*
*Jose Valencia added for RIC-3, effective July 2026 (previously unassigned).*
*Marco Garmendia added for RIC-10, effective July 2026 — new multi-state territory covering unmanaged areas across states; no dedicated ISR (absent from ISR → Territory table).*

*Jeremy Moore (departed end of April 2026) is no longer in `OSR_ROSTER`. Frozen Jan–Apr 2026 dashboards still show him historically.*
*Mariana Gross added June 2026, assigned RIC-5 (Phoenix Metro, AZ; previously unassigned).*

## ISR Roster (as of July 2026)

Connor Admirand, Katie Anguiano, Laura Angulo, Lesly Arroyo, Michael Palmer, Noemy Carrion — all report to Luz Vigil (ISR Supervisor).

*Javier Gonzalez departed (absent from Territory_Overview_v1.9 pairings; zero June Genesys data). His LTO-1/LTO-5 coverage moved to Laura Angulo.*

## ISR → Territory Assignments

Per **Territory_Overview_v1.9** (June 2026), "ISR Pairings — Phase 1". Open territories keep ISR coverage until reassigned.

| ISR | Territories |
|-----|-------------|
| Katie Anguiano | RIC-1 (Cesar), RIC-2 (Claudia), RIC-4 (Richard) — drops RIC-1 when ISR #8 hired |
| Lesly Arroyo | RIC-3 (Jose), RIC-5 (Mariana), RIC-6 (Phillip) — drops RIC-3 when ISR #8 hired |
| Laura Angulo | LTO-1 (Yemaira), LTO-5 (Jared), LTO-8 (open) — drops LTO-8 when TSR fills |
| Noemy Carrion | LTO-2 (Omar), LTO-3 (Joseph), LTO-4 (open) — drops LTO-4 when ISR #7 hired |
| Connor Admirand | LTO-6 (Stephanie), RIC-8 (Eric) |
| Michael Palmer | RIC-7 (open), RIC-9 (Matthew) |

## Territory → OSR Mapping

| Territory | OSR | State/Area |
|-----------|-----|------------|
| LTO-1 | Yemaira Hernandez | FL (Miami-Dade/Broward) |
| LTO-2 | Omar Corona | TX (S. Houston/Valley/El Paso) |
| LTO-3 | Joseph Guerra | TX (State Manager) |
| LTO-5 | Jared Midkiff | FL (State Manager) |
| LTO-6 | Stephanie Whitlock | GA/NE FL/Panhandle *(SF re-coded LTO-7 → LTO-6, June 2026)* |
| RIC-1 | Cesar Flores | CA (LA Metro Core) |
| RIC-2 | Claudia Gerhardt | CA (IE South/San Diego) |
| RIC-3 | Jose Valencia | CA *(effective July 2026)* |
| RIC-4 | Richard Herrera | CA (Orange County/SE LA) |
| RIC-5 | Mariana Gross | AZ (Phoenix Metro) |
| RIC-6 | Phillip Mason | CA (Sacramento/NorCal) |
| RIC-8 | Eric Henderson | PA (4 Metros) |
| RIC-9 | Matthew MacDonald | AZ (State Manager + NM/UT/ID) |
| RIC-10 | Marco Garmendia | Multi-state (unmanaged areas) *(effective July 2026; no dedicated ISR)* |

**Unassigned territories:** LTO-4, LTO-8, RIC-7 — hiring in progress. **Retired code:** LTO-7 (renamed to LTO-6 in SF, June 2026; Stephanie's Jan–Mar cohort history remains frozen under LTO-7).

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

**Roster changes** (all in `automation/config.py` unless noted):
1. Update `OSR_ROSTER` (or `ISR_ROSTER`)
2. If the rep has a territory: update `TERRITORY_MAP` (OSR) and/or `ISR_TERRITORY_MAP` (ISR)
3. **Update `OSR_EMAILS`** — keys must stay in sync with `OSR_ROSTER` (adding a rep without an email entry, or leaving a departed rep's entry, breaks/misfires the weekly cohort email)
4. Update the embedded `TERRITORY_MAP` in `html_generator.py` (the territory-review page has its own copy with area labels)
5. Update the roster/territory/ISR sections in this file
6. Removals follow the "Jeremy Moore precedent": drop from roster + maps + emails, territory becomes unassigned; frozen past-month dashboards keep the departed rep historically. New hires with a future effective date can be added immediately — credit only flows once SF's `OSR Enrollment Credit` names them.

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
