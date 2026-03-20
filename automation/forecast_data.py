"""
Sales budget forecast data — manually updated from Kevin's sales budget Excel workbook.

Contains territory-level monthly budget targets and actuals for funded volume ($).
Used by forecast/pacing dashboards to calculate variance, run-rate, and projections.

Update this file when:
- New actuals come in (monthly close or MTD refresh)
- Budget targets are revised
- Territories are added or reassigned

LAST_UPDATED should always reflect the date of the most recent data refresh.
"""

# Date of last data refresh (YYYY-MM-DD)
LAST_UPDATED = "2026-03-20"

# Current MTD month (1-indexed). Months before this are complete; this month is partial.
# E.g., MTD_MONTH = 3 means Jan & Feb are finalized, March is month-to-date.
MTD_MONTH = 3

# ─── Monthly Budget Targets by Territory ────────────────────────────────────
# Each key is a territory code. Values are a 12-element list of monthly funded $
# targets for Jan–Dec 2026, in order [Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec].
TERRITORY_BUDGETS = {
    "LTO-1": [503587, 498333, 594160, 598325, 570972, 622599, 648864, 656292, 660456, 699402, 662631, 733095],
    "LTO-2": [530056, 524443, 626167, 625514, 597441, 654246, 676053, 687939, 687286, 726592, 693559, 760284],
    "LTO-3": [447433, 445136, 532838, 536258, 514818, 564234, 586796, 597927, 601346, 637335, 610180, 671028],
    "LTO-5": [821160, 802747, 951648, 942216, 888545, 966928, 992755, 1000620, 991189, 1043294, 980641, 1076987],
    "LTO-7": [312342, 315140, 379257, 390979, 379727, 415747, 441518, 449439, 461161, 492057, 471880, 525749],
    "RIC-2": [659707, 649390, 774120, 764573, 727092, 797495, 815112, 831188, 821641, 865651, 827399, 899343],
    "RIC-4": [550658, 528695, 622432, 600201, 567505, 634161, 645124, 667854, 656853, 695663, 674465, 729356],
    "RIC-6": [512818, 490996, 581173, 573308, 546511, 604274, 623847, 637967, 635717, 674385, 644862, 708078],
    "RIC-7": [652510, 631284, 751960, 739885, 703049, 775658, 790423, 809350, 797275, 840962, 806207, 874655],
    "RIC-8": [1154592, 1114433, 1322762, 1279835, 1205131, 1327526, 1330374, 1361218, 1318291, 1380912, 1320207, 1414605],
    "RIC-9": [1359063, 1320225, 1562751, 1520972, 1426448, 1557605, 1571510, 1591297, 1549518, 1622049, 1530467, 1655742],
}

# ─── Actuals by Territory ───────────────────────────────────────────────────
# Funded $ actuals per territory. List length = MTD_MONTH.
# Months before MTD_MONTH are finalized; the last element is month-to-date (partial).
# E.g., with MTD_MONTH=3: [Jan_final, Feb_final, Mar_MTD]
TERRITORY_ACTUALS = {
    "LTO-1": [566026, 467230, 281809],
    "LTO-2": [546139, 544843, 275815],
    "LTO-3": [518614, 526881, 251110],
    "LTO-5": [856926, 862558, 370764],
    "LTO-7": [301797, 275447, 138025],
    "RIC-2": [611670, 532998, 244561],
    "RIC-4": [515331, 490612, 212889],
    "RIC-6": [412572, 438217, 163812],
    "RIC-7": [641561, 717852, 329492],
    "RIC-8": [1046773, 1033476, 496105],
    "RIC-9": [1279184, 1376826, 588622],
}
