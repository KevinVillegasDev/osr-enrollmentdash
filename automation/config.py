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
ISR_ROSTER = [
    "Connor Admirand",
    "Javier Gonzalez",
    "Katie Anguiano",
    "Laura Angulo",
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

# ─── OSR Roster (as of March 2026) ───────────────────────────────────────────
OSR_ROSTER = [
    "Cesar Flores",
    "Claudia Gerhardt",
    "DeLon Phoenix",
    "Eric Henderson",
    "Jared Midkiff",
    "Jeremy Moore",
    "Joseph Guerra",
    "Matthew MacDonald",
    "Omar Corona",
    "Phillip Mason",
    "Stephanie Whitlock",
    "Yemaira Hernandez",
    "Outside Sales Manager",
]

# ─── Territory → OSR Mapping ────────────────────────────────────────────────
# Maps territory codes from the sales budget to OSR names.
# Unassigned territories (LTO-4, LTO-8, RIC-3, RIC-5) are excluded.
# LTO-4 was Sara Porter (no longer on team); Jeremy Moore took RIC-4.
# Cesar Flores assigned RIC-1.
TERRITORY_MAP = {
    "LTO-1": "Yemaira Hernandez",
    "LTO-2": "Omar Corona",
    "LTO-3": "Joseph Guerra",
    "LTO-5": "Jared Midkiff",
    "LTO-7": "Stephanie Whitlock",
    "RIC-1": "Cesar Flores",
    "RIC-2": "Claudia Gerhardt",
    "RIC-4": "Jeremy Moore",
    "RIC-6": "Phillip Mason",
    "RIC-7": "DeLon Phoenix",
    "RIC-8": "Eric Henderson",
    "RIC-9": "Matthew MacDonald",
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
    "isr_note_account": "_label_Company / Account",
    "isr_note_branch_id": "Branch ID",
    "isr_note_rep": "_label_Assigned",
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
