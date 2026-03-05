# EasyPay Finance - OSR Dashboard Hub

## What This Is

A static HTML dashboard hub for EasyPay Finance's outside sales team (OSR) performance tracking. Deployed on Netlify via GitHub. No build step, no framework, no dependencies beyond Chart.js (loaded from CDN). Every page is a self-contained HTML file with inline CSS and JS.

The primary user is Kevin (Sales Program Manager). The dashboards track merchant enrollment, production (funded volume), commission compliance, quarterly targets, and field activity for ~12 outside sales reps.

## File Structure

```
index.html              - Landing page / dashboard hub
jan-2026.html           - January 2026 monthly dashboard
feb-2026.html           - February 2026 monthly dashboard
cohort-tracking.html    - Cohort commission tracker (tabbed: active + baseline)
q1-enrollment.html      - Q1 2026 enrollment compliance tracker
field-activity.html     - Weekly field check-in tracker (Maps data)
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

Charts: Chart.js 4.x loaded from CDN. Used on monthly dashboards (jan/feb) for bar charts, doughnut charts, and daily trend lines.

## Monthly Dashboard Pattern (jan-2026.html, feb-2026.html)

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

**To add a new month:** Duplicate the most recent month's HTML, replace all data variables in the `<script>` block, update hardcoded values in the function section (enrollment counts in toggle buttons, product mix numbers, funnel numbers, observations text, bars init values). Update index.html to add the new month card and update YTD summary.

## Commission Tracking (cohort-tracking.html)

Tracks OSR compliance with Paul Funchess's commission structure:

**Rules:**
- Each monthly enrollment cohort must generate $15,000 in funded volume by end of Month 1
- Month 0 = enrollment month, Month 1 = first full calendar month after enrollment
- Funding from BOTH Month 0 and Month 1 counts toward the $15K target
- If an OSR misses $15K by end of Month 1, they get a Month 2 true-up: hit $30K cumulative by end of Month 2
- Only OSR-credited merchants count (non-credited enrollments excluded)

**Structure:**
- Tabbed interface: one tab per cohort
- Active cohort (orange tab): the current month's enrollees being tracked
- Baseline/completed cohorts (gray dimmed tab): finalized or pre-structure cohorts
- Each tab shows: KPIs, progress bars per OSR, expandable merchant drilldowns with per-month funding columns

**Current cohorts:**
- Feb → Mar (Active): Feb enrollees, $15K deadline end of March, M2 true-up end of April
- Jan → Feb (Baseline): Pre-commission-structure, retroactive tracking for comparison

**When a new month starts:** Add a new tab for the new cohort (e.g., "Mar → Apr"). Move the previous active cohort's tab to non-dimmed completed state. The JS data arrays are `janCohort` and `febCohort` - add `marCohort` etc following the same pattern.

## Q1 Enrollment Compliance (q1-enrollment.html)

Tracks per-OSR quarterly enrollment targets:

**Rules:**
- 30 enrollments per quarter per OSR
- No single month below 10 (floor)
- Quarterly true-up: if any month falls below 10 but quarter total hits 30, no penalty
- Resets at start of each quarter

**Current:** Q1 2026 = Jan + Feb + Mar. March column shows "-" (in progress).

**When Q2 starts:** Freeze Q1 page as final record. Create q2-enrollment.html with fresh data. Update index.html to link to both (Q1 as archived, Q2 as active).

## Field Activity Tracker (field-activity.html)

Weekly check-in data from Salesforce Maps.

**Data source:** Maps_Check_Ins_This_Week report (exported as Excel)

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
2. Commission Tracking (cohort production card + Q1 enrollment compliance card)
3. Field Activity (weekly check-ins card)
4. Monthly Dashboards (cards per month, auto-collapses after 3 most recent)

**When updating:** YTD summary is hardcoded and must be manually updated when new months are added. Monthly dashboard cards are also hardcoded with summary KPIs from each month.

## Data Flow

Current (manual):
1. Kevin exports 4 Salesforce reports as Excel files
2. Claude processes Excel → generates HTML with embedded data
3. Kevin uploads HTML files to Netlify (via GitHub push or drag-and-drop)

Future (automated):
1. GitHub Actions workflow runs nightly at 11pm
2. Authenticates to Salesforce via Connected App (OAuth)
3. Pulls 5 reports via Salesforce REST API
4. Python script processes report data → rebuilds HTML pages
5. Commits to GitHub → Netlify auto-deploys
6. End-of-month snapshot saves data as JSON archive before relative date filters roll

## Salesforce Reports Needed

| # | Report Name | Key Filters | Purpose |
|---|-------------|-------------|---------|
| 1 | New_Enrollments_by_Month | Enrollment Date = THIS MONTH, Record Type = Branch | Total company enrollments |
| 2 | Credited_Sales_Team_Enrollments | Enrollment Date = THIS MONTH, Record Type = Branch, OSR Enrollment Credit != blank | OSR-credited enrollments |
| 3 | Current_Month_Enrollment_Activity_Report | Enrollment Date = THIS MONTH, Record Type = Branch | Month 0 funding |
| 4 | Last_Month_Enrollment_Activity_Report | Enrollment Date = LAST MONTH, Record Type = Branch | Month 1 funding (multi-month columns) |
| 5 | Maps_Check_Ins_This_Week | Date = THIS WEEK | Field check-in activity |

For historical cohorts or Month 2 true-up data, Report 4's template is called with filter overrides to specify the exact enrollment date range needed.

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

**Add a new monthly dashboard:**
1. Process 4 Salesforce reports for the month
2. Duplicate most recent month's HTML file
3. Replace all JS data variables
4. Update all hardcoded values in function section
5. Add month card to index.html
6. Update YTD summary on index.html
7. Update cohort-tracking.html with new cohort tab
8. Update q1-enrollment.html (or create new quarterly page)

**Update field activity:**
1. Export Maps_Check_Ins_This_Week report
2. Process and deduplicate check-in data
3. Rebuild field-activity.html with new data
4. Update field activity card on index.html

**End of quarter:**
1. Freeze current quarterly enrollment page as final
2. Create new quarterly page
3. Update index.html commission tracking section
