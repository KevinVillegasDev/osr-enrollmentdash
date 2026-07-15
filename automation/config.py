"""
Configuration constants for the OSR Dashboard automation pipeline.
Report IDs, OSR roster, month mappings, color palette, and Salesforce field names.
"""

import os

# ─── Salesforce Connection ───────────────────────────────────────────────────
SF_LOGIN_URL = os.environ.get("SF_LOGIN_URL", "https://login.salesforce.com")
SF_CLIENT_ID = os.environ.get("SF_CLIENT_ID", "")
SF_CLIENT_SECRET = os.environ.get("SF_CLIENT_SECRET", "")
SF_API_VERSION = "v62.0"

# ─── Genesys Cloud Connection ────────────────────────────────────────────────
GENESYS_REGION = os.environ.get("GENESYS_REGION", "usw2.pure.cloud")
GENESYS_CLIENT_ID = os.environ.get("GENESYS_CLIENT_ID", "")
GENESYS_CLIENT_SECRET = os.environ.get("GENESYS_CLIENT_SECRET", "")

# ─── ISR Roster ──────────────────────────────────────────────────────────────
# Inside sales reps tracked via Genesys Cloud talk time.
# Names must match exactly how they appear in Genesys Cloud.
# Update this list when ISRs join or leave the team.
# 6 ISRs per Territory_Overview_v1.9 (June 2026), reporting to Luz Vigil.
# Javier Gonzalez departed (absent from v1.9 pairings; zero June Genesys data).
ISR_ROSTER = [
    "Connor Admirand",
    "Katie Anguiano",
    "Laura Angulo",
    "Lesly Arroyo",
    "Michael Palmer",
    "Noemy Carrion",
]

# ─── Salesforce Report IDs ───────────────────────────────────────────────────
# Kevin: Replace these placeholder values with your 18-character Salesforce Report IDs.
# Find them by opening each report in Salesforce and copying the ID from the URL:
#   https://yourinstance.lightning.force.com/lightning/r/Report/{REPORT_ID}/view
REPORT_IDS = {
    "new_enrollments": os.environ.get("SF_REPORT_NEW_ENROLLMENTS", "00OTO000009L49t2AC"),
    "credited_enrollments": os.environ.get("SF_REPORT_CREDITED_ENROLLMENTS", "00OTO000007Mhrt2AC"),
    "current_month_activity": os.environ.get("SF_REPORT_CURRENT_MONTH_ACTIVITY", "00OTO00000671Gr2AI"),
    "last_month_activity": os.environ.get("SF_REPORT_LAST_MONTH_ACTIVITY", "00OTO000009Iw1x2AC"),
    "maps_check_ins": os.environ.get("SF_REPORT_MAPS_CHECK_INS", "00OTO000009NEbN2AW"),
    "monthly_quota": os.environ.get("SF_REPORT_MONTHLY_QUOTA", "00OTO000009YYWj2AO"),
    "isr_notes": os.environ.get("SF_REPORT_ISR_NOTES", "00O8Y0000098j62UAA"),
}

# ─── OSR Roster (as of June 2026) ────────────────────────────────────────────
# Jeremy Moore departed end of April 2026; Richard Herrera took over RIC-4 starting May 2026.
# Frozen Jan–Apr 2026 dashboards still show Jeremy historically — those HTMLs are never regenerated.
# Mariana Gross added June 2026 (RIC-5 — Phoenix Metro).
# Francisco Gonzalez (LTO-4) and DeLon Phoenix (RIC-7) removed June 2026; their
# territories are now unassigned. Frozen past-month dashboards still show them historically.
# Jose Valencia added for RIC-3, effective July 2026 (previously unassigned).
# Marco Garmendia added for RIC-10, effective July 2026 — NEW multi-state
# territory covering unmanaged areas across states; no dedicated ISR.
OSR_ROSTER = [
    "Cesar Flores",
    "Claudia Gerhardt",
    "Eric Henderson",
    "Jared Midkiff",
    "Jose Valencia",
    "Joseph Guerra",
    "Marco Garmendia",
    "Mariana Gross",
    "Matthew MacDonald",
    "Omar Corona",
    "Phillip Mason",
    "Richard Herrera",
    "Stephanie Whitlock",
    "Yemaira Hernandez",
    "Outside Sales Manager",
]

# ─── Territory → OSR Mapping ────────────────────────────────────────────────
# Maps territory codes from the sales budget to OSR names.
# Unassigned territories (LTO-4, LTO-8, RIC-7) are excluded.
# LTO-4: Sara Porter → Francisco Gonzalez (removed June 2026); now unassigned.
# RIC-3: Jose Valencia, effective July 2026 (CA; previously unassigned).
# RIC-4: Jeremy Moore through April 2026; Richard Herrera from May 2026 forward.
# RIC-5: Mariana Gross from June 2026 (Phoenix Metro, AZ; previously unassigned).
# RIC-7: DeLon Phoenix (removed June 2026); now unassigned.
# RIC-10: Marco Garmendia, effective July 2026 (NEW territory — multi-state
#         unmanaged areas; no dedicated ISR, so absent from ISR_TERRITORY_MAP).
# LTO-6: Stephanie Whitlock — SF re-coded her territory LTO-7 → LTO-6 in June
#        2026 (confirmed by Sales Ops; same GA/NE FL/Panhandle book). Her
#        Jan–Mar cohorts are frozen under the old LTO-7 code and stay intact.
TERRITORY_MAP = {
    "LTO-1": "Yemaira Hernandez",
    "LTO-2": "Omar Corona",
    "LTO-3": "Joseph Guerra",
    "LTO-5": "Jared Midkiff",
    "LTO-6": "Stephanie Whitlock",
    "RIC-1": "Cesar Flores",
    "RIC-2": "Claudia Gerhardt",
    "RIC-3": "Jose Valencia",
    "RIC-4": "Richard Herrera",
    "RIC-5": "Mariana Gross",
    "RIC-6": "Phillip Mason",
    "RIC-8": "Eric Henderson",
    "RIC-9": "Matthew MacDonald",
    "RIC-10": "Marco Garmendia",
}

# ─── Hybrid-Role Reps ────────────────────────────────────────────────────────
# Reps working a mixed inside/outside role, tracked on the index-page Hybrid
# Role Tracker widget: Salesforce notes (Report 7, _label_ISR), Maps check-ins
# (Report 5), and Genesys talk time (once the rep is set up in Genesys — the
# widget shows "pending setup" until their name appears in the Genesys data).
# Keys must match the name exactly as it appears in Salesforce and Genesys.
HYBRID_REPS = {
    "Marco Garmendia": "RIC-10",
}

# ─── Territory → ISR Mapping ────────────────────────────────────────
# Maps territory codes to assigned ISR names.
# Source of truth: Territory_Overview_v1.9 (June 2026) "ISR Pairings — Phase 1".
# Open territories (LTO-4, LTO-8, RIC-7) keep active ISR coverage per v1.9
# even with no TSR assigned — entries below are inert for cohort math (which
# keys off TERRITORY_MAP) but document real coverage.
# Note: v1.9 labels Stephanie's book LTO-7; SF re-coded it LTO-6 (June 2026),
# so the LTO-6 key below is deliberate.
# Phase 2 plan (not yet active): ISR #7 hire takes LTO-4 from Noemy;
# ISR #8 hire takes RIC-1 from Katie and RIC-3 from Lesly.
ISR_TERRITORY_MAP = {
    "LTO-1": "Laura Angulo",
    "LTO-2": "Noemy Carrion",
    "LTO-3": "Noemy Carrion",
    "LTO-4": "Noemy Carrion",      # territory OPEN — ISR coverage continues
    "LTO-5": "Laura Angulo",
    "LTO-6": "Connor Admirand",
    "LTO-8": "Laura Angulo",       # territory OPEN — ISR coverage continues
    "RIC-1": "Katie Anguiano",
    "RIC-2": "Katie Anguiano",
    "RIC-3": "Lesly Arroyo",
    "RIC-4": "Katie Anguiano",
    "RIC-5": "Lesly Arroyo",
    "RIC-6": "Lesly Arroyo",
    "RIC-7": "Michael Palmer",     # territory OPEN — ISR coverage continues
    "RIC-8": "Connor Admirand",
    "RIC-9": "Michael Palmer",
}

# ─── Month Mappings ──────────────────────────────────────────────────────────
MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}

MONTH_ABBREV = {
    1: "jan", 2: "feb", 3: "mar", 4: "apr",
    5: "may", 6: "jun", 7: "jul", 8: "aug",
    9: "sep", 10: "oct", 11: "nov", 12: "dec",
}

# ─── Color Palette ───────────────────────────────────────────────────────────
COLORS = {
    "blue": "#3B82F6",
    "green": "#10B981",
    "amber": "#F59E0B",
    "purple": "#8B5CF6",
    "cyan": "#06B6D4",
    "red": "#EF4444",
}

# Chart.js palette for doughnuts/bars
CHART_PALETTE = [
    "#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6",
    "#06B6D4", "#EC4899", "#F97316", "#14B8A6", "#A855F7",
    "#6366F1", "#84CC16",
]

# ─── Commission Rules ────────────────────────────────────────────────────────
COHORT_TARGET_M1 = 15000    # $15K by end of Month 1
COHORT_TARGET_M2 = 30000    # $30K by end of Month 2 (true-up)
QUARTERLY_TARGET = 30       # 30 enrollments per quarter
MONTHLY_FLOOR = 10          # No single month below 10

# ─── Cohort Email Distribution ───────────────────────────────────────────────
# OSR email addresses for the weekly cohort email. Keys must match OSR_ROSTER.
# Leave a value as "" to skip sending to that rep (e.g., departed, manager).
OSR_EMAILS = {
    "Cesar Flores": "cesar.flores@easypayfinance.com",
    "Claudia Gerhardt": "claudia.gerhardt@easypayfinance.com",
    "Eric Henderson": "eric.henderson@easypayfinance.com",
    "Jared Midkiff": "jared.midkiff@easypayfinance.com",
    "Jose Valencia": "jose.valencia@easypayfinance.com",
    "Joseph Guerra": "joseph.guerra@easypayfinance.com",
    "Marco Garmendia": "marco.garmendia@easypayfinance.com",
    "Mariana Gross": "mariana.gross@easypayfinance.com",
    "Matthew MacDonald": "matthew.macdonald@easypayfinance.com",
    "Omar Corona": "omar.corona@easypayfinance.com",
    "Phillip Mason": "phillip.mason@easypayfinance.com",
    "Richard Herrera": "richard.herrera@easypayfinance.com",
    "Stephanie Whitlock": "stephanie.whitlock@easypayfinance.com",
    "Yemaira Hernandez": "yemaira.hernandez@easypayfinance.com",
    "Outside Sales Manager": "",  # manager/overflow account — skip
}

# Local OneDrive path where the email script drops JSON envelopes.
# Power Automate watches this folder and sends the actual emails.
COHORT_EMAIL_OUTBOX = os.environ.get(
    "COHORT_EMAIL_OUTBOX",
    r"C:\Users\kevin.villegas\OneDrive - Duvera\OSR Reports\Outbox",
)

# Kevin's address — used for --test sends and as a BCC on real sends if desired.
COHORT_EMAIL_ADMIN = "kevin.v@easypayfinance.com"

# ─── Salesforce Report Column Names ──────────────────────────────────────────
# These are the API names of columns in the Salesforce reports.
# If column names differ in your org, update them here.
# The actual mapping will be done dynamically by reading reportExtendedMetadata,
# but these are the expected label patterns for matching.
COLUMN_LABELS = {
    # Report 1 & 2: Enrollment reports
    "branch_id": "Branch ID",
    "merchant_name": "Account Name",
    "enrollment_date": "Enrollment Date",
    "billing_state": "Billing State/Province",
    "billing_city": "Billing City",
    "industry": "Industry",
    "osr_credit": "OSR Enrollment Credit",
    "isr_assignment": "ISR",
    "product_type": "EPF Product",
    "os_territory": "_label_OS Territory",
    # Report 3 & 4: Activity reports (matrix/summary format)
    # Report 4 is grouped by Account Name + Branch ID, with column group "First Date of Month"
    # Metric columns within each month group:
    "funded_dollars": "# Funded Dollars",
    "funded_apps": "# Funded Applications Total",
    "total_apps": "# Applications",
    "funded_avg": "# Funded Average",
    "mmd_number": "Monthly Merchant Data: MMD Number",
    # Report 5: Field activity (Maps check-ins via Salesforce API)
    # API returns _label_ prefixed keys for display values
    "check_in_date": "_label_Created Date/Time",
    "check_in_rep": "_label_Assigned",
    "stop_name": "_label_Company / Account",
    "stop_comment": "_label_Full Comments",
    "stop_location": "",  # Not available in API response
    "lead_field": "Lead",  # null = Account (existing), non-null = Lead (prospect)
    # Report 7: ISR Notes / Touch Points
    "isr_note_account": "_label_Account Name",
    "isr_note_branch_id": "Branch ID",
    "isr_note_rep": "_label_ISR",
    "isr_note_subject": "_label_Subject",
    "isr_note_comments": "_label_Full Comments",
    "isr_note_date": "_label_Created Date",
}

# ─── File Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def month_filename(month: int, year: int) -> str:
    """Generate the HTML filename for a given month/year, e.g. 'feb-2026.html'."""
    return f"{MONTH_ABBREV[month]}-{year}.html"


def month_filepath(month: int, year: int) -> str:
    """Full path to a monthly dashboard HTML file."""
    return os.path.join(PROJECT_ROOT, month_filename(month, year))
