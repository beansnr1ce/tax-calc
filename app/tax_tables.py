"""
Tax tables and brackets for 2025 and 2026.
Sources:
- Federal: IRS Revenue Procedures (inflation-adjusted)
- California: California Franchise Tax Board
"""

# Federal Tax Brackets 2025
# Source: IRS Rev. Proc. 2024-40 (inflation adjustments)
FEDERAL_BRACKETS_2025 = {
    'single': [
        (11925, 0.10),
        (48475, 0.12),
        (103350, 0.22),
        (197300, 0.24),
        (250525, 0.32),
        (626350, 0.35),
        (float('inf'), 0.37)
    ],
    'married_jointly': [
        (23850, 0.10),
        (96950, 0.12),
        (206700, 0.22),
        (394600, 0.24),
        (501050, 0.32),
        (751600, 0.35),
        (float('inf'), 0.37)
    ],
    'head_of_household': [
        (17000, 0.10),
        (64850, 0.12),
        (103350, 0.22),
        (197300, 0.24),
        (250500, 0.32),
        (626350, 0.35),
        (float('inf'), 0.37)
    ]
}

# Federal Tax Brackets 2026 (estimated ~2.8% inflation adjustment)
FEDERAL_BRACKETS_2026 = {
    'single': [
        (12250, 0.10),
        (49825, 0.12),
        (106250, 0.22),
        (202825, 0.24),
        (257525, 0.32),
        (643900, 0.35),
        (float('inf'), 0.37)
    ],
    'married_jointly': [
        (24500, 0.10),
        (99650, 0.12),
        (212500, 0.22),
        (405650, 0.24),
        (515100, 0.32),
        (772650, 0.35),
        (float('inf'), 0.37)
    ],
    'head_of_household': [
        (17475, 0.10),
        (66675, 0.12),
        (106250, 0.22),
        (202825, 0.24),
        (257500, 0.32),
        (643900, 0.35),
        (float('inf'), 0.37)
    ]
}

# California Tax Brackets 2025
# Source: California FTB (inflation-adjusted)
CA_BRACKETS_2025 = {
    'single': [
        (10756, 0.01),
        (25499, 0.02),
        (40243, 0.04),
        (55866, 0.06),
        (70606, 0.08),
        (360659, 0.093),
        (432791, 0.103),
        (721319, 0.113),
        (float('inf'), 0.123)
    ],
    'married_jointly': [
        (21512, 0.01),
        (50998, 0.02),
        (80486, 0.04),
        (111732, 0.06),
        (141212, 0.08),
        (721318, 0.093),
        (865582, 0.103),
        (1442638, 0.113),
        (float('inf'), 0.123)
    ],
    'head_of_household': [
        (21527, 0.01),
        (51011, 0.02),
        (65755, 0.04),
        (81378, 0.06),
        (96118, 0.08),
        (490493, 0.093),
        (588593, 0.103),
        (980987, 0.113),
        (float('inf'), 0.123)
    ]
}

# California Tax Brackets 2026 (estimated ~2.5% inflation adjustment)
CA_BRACKETS_2026 = {
    'single': [
        (11025, 0.01),
        (26137, 0.02),
        (41249, 0.04),
        (57258, 0.06),
        (72371, 0.08),
        (369676, 0.093),
        (443611, 0.103),
        (739352, 0.113),
        (float('inf'), 0.123)
    ],
    'married_jointly': [
        (22050, 0.01),
        (52273, 0.02),
        (82498, 0.04),
        (114526, 0.06),
        (144742, 0.08),
        (739351, 0.093),
        (887222, 0.103),
        (1478704, 0.113),
        (float('inf'), 0.123)
    ],
    'head_of_household': [
        (22065, 0.01),
        (52286, 0.02),
        (67399, 0.04),
        (83412, 0.06),
        (98521, 0.08),
        (502755, 0.093),
        (603308, 0.103),
        (1005512, 0.113),
        (float('inf'), 0.123)
    ]
}

# California Mental Health Services Tax (additional 1% on income over $1M)
CA_MENTAL_HEALTH_THRESHOLD = 1000000

# Standard Deductions
FEDERAL_STANDARD_DEDUCTION = {
    2025: {
        'single': 15000,
        'married_jointly': 30000,
        'head_of_household': 22500
    },
    2026: {
        'single': 15400,
        'married_jointly': 30800,
        'head_of_household': 23100
    }
}

# California Standard Deduction
CA_STANDARD_DEDUCTION = {
    2025: {
        'single': 5540,
        'married_jointly': 11080,
        'head_of_household': 11080
    },
    2026: {
        'single': 5680,
        'married_jointly': 11360,
        'head_of_household': 11360
    }
}

# California Personal Exemption Credit
CA_EXEMPTION_CREDIT = {
    2025: {
        'single': 144,
        'married_jointly': 288,
        'head_of_household': 144
    },
    2026: {
        'single': 148,
        'married_jointly': 296,
        'head_of_household': 148
    }
}

# CA SDI (State Disability Insurance) Rate
# 2025: 1.2% on first $174,668
# 2026: Estimated 1.1% on first $180,000 (estimate)
CA_SDI = {
    2025: {
        'rate': 0.012,
        'wage_base': 174668
    },
    2026: {
        'rate': 0.011,
        'wage_base': 180000
    }
}

# Self-Employment Tax Rate
SELF_EMPLOYMENT_TAX_RATE = 0.153  # 15.3% (12.4% Social Security + 2.9% Medicare)
SELF_EMPLOYMENT_SS_WAGE_BASE = {
    2025: 176100,
    2026: 181200  # Estimated
}

# Child Tax Credit
CHILD_TAX_CREDIT = {
    'under_17': 2000,
    'other_dependent': 500,
    'phase_out_start': {
        'single': 200000,
        'married_jointly': 400000,
        'head_of_household': 200000
    },
    'phase_out_rate': 50  # $50 per $1000 over threshold
}

# Student Loan Interest Deduction
STUDENT_LOAN_INTEREST = {
    'max_deduction': 2500,
    'phase_out_start': {
        2025: {
            'single': 80000,
            'married_jointly': 165000,
            'head_of_household': 80000
        },
        2026: {
            'single': 82000,
            'married_jointly': 169000,
            'head_of_household': 82000
        }
    },
    'phase_out_range': {
        'single': 15000,
        'married_jointly': 30000,
        'head_of_household': 15000
    }
}

# IRA Contribution Limits
IRA_LIMITS = {
    2025: {
        'regular': 7000,
        'catch_up_50plus': 8000
    },
    2026: {
        'regular': 7000,
        'catch_up_50plus': 8000
    }
}

# 401(k) Contribution Limits
_401K_LIMITS = {
    2025: {
        'regular': 23500,
        'catch_up_50plus': 31000
    },
    2026: {
        'regular': 24000,
        'catch_up_50plus': 31500
    }
}

# HSA Contribution Limits
HSA_LIMITS = {
    2025: {
        'individual': 4300,
        'family': 8550
    },
    2026: {
        'individual': 4400,
        'family': 8750
    }
}

# SALT Cap (State and Local Tax Deduction)
SALT_CAP = 10000

# Pay Frequencies
PAY_FREQUENCIES = {
    'weekly': 52,
    'biweekly': 26,
    'semimonthly': 24,
    'monthly': 12,
    'quarterly': 4,
    'annually': 1
}

# Quarterly Estimated Tax Due Dates
QUARTERLY_DUE_DATES = {
    2025: [
        ('Q1', 'April 15, 2025'),
        ('Q2', 'June 16, 2025'),
        ('Q3', 'September 15, 2025'),
        ('Q4', 'January 15, 2026')
    ],
    2026: [
        ('Q1', 'April 15, 2026'),
        ('Q2', 'June 15, 2026'),
        ('Q3', 'September 15, 2026'),
        ('Q4', 'January 15, 2027')
    ]
}


def get_federal_brackets(year, filing_status):
    """Get federal tax brackets for a given year and filing status."""
    if year == 2025:
        return FEDERAL_BRACKETS_2025.get(filing_status, FEDERAL_BRACKETS_2025['single'])
    else:
        return FEDERAL_BRACKETS_2026.get(filing_status, FEDERAL_BRACKETS_2026['single'])


def get_ca_brackets(year, filing_status):
    """Get California tax brackets for a given year and filing status."""
    if year == 2025:
        return CA_BRACKETS_2025.get(filing_status, CA_BRACKETS_2025['single'])
    else:
        return CA_BRACKETS_2026.get(filing_status, CA_BRACKETS_2026['single'])
