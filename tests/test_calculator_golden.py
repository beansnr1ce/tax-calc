"""
Golden/characterization tests for tax_calculator.calculate_all().

These pin the CURRENT behavior of the calculator before we migrate
its constants from tax_tables.py to the TaxTableRegistry. After the
migration, all assertions must still pass — any regression means the
registry-backed implementation changed a result.

Once the migration is complete and trusted, these tests should be
re-anchored to assert against authoritative IRS/FTB values rather
than legacy implementation quirks.
"""

from app.tax_calculator import calculate_all


def _approx(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


def test_single_w2_only_2025():
    """Single filer, $80k W-2 biweekly, no deductions, no dependents."""
    result = calculate_all(
        {
            "tax_year": 2025,
            "filing_status": "single",
            "salary1_gross": 80000 / 26,
            "salary1_frequency": "biweekly",
        }
    )

    fed = result["federal"]
    assert _approx(fed["gross_income"], 80000.00, 0.10)
    assert _approx(fed["agi"], 80000.00, 0.10)
    assert fed["standard_deduction"] == 15000
    # taxable = 80000 - 15000 = 65000
    # 10% * 11925 + 12% * (48475-11925) + 22% * (65000-48475)
    # = 1192.50 + 4386.00 + 3635.50 = 9214.00
    assert _approx(fed["tax_before_credits"], 9214.00, 0.10)
    assert fed["child_tax_credit"]["total"] == 0
    assert _approx(fed["final_tax"], 9214.00, 0.10)


def test_married_jointly_dual_income_with_401k_2025():
    """MFJ, dual income $120k + $90k, both maxing 401k, 2 children under 17."""
    result = calculate_all(
        {
            "tax_year": 2025,
            "filing_status": "married_jointly",
            "salary1_gross": 120000 / 26,
            "salary1_frequency": "biweekly",
            "dual_income": True,
            "salary2_gross": 90000 / 26,
            "salary2_frequency": "biweekly",
            "pretax_deductions_1": {"input_type": "annual", "_401k": 23500},
            "pretax_deductions_2": {"input_type": "annual", "_401k": 23500},
            "children_under_17": 2,
        }
    )

    fed = result["federal"]
    # gross = 210000, pretax = 47000, agi = 163000
    assert _approx(fed["gross_income"], 210000.00, 0.10)
    assert _approx(fed["agi"], 163000.00, 0.10)
    assert fed["standard_deduction"] == 30000
    # MFJ 2025 CTC: 2 * 2000 = 4000, AGI 163000 < 400000 threshold => full credit
    assert fed["child_tax_credit"]["total"] == 4000


def test_single_with_1099nec_self_employment_2025():
    """Single, $50k W-2 + $40k 1099-NEC. SE tax should kick in."""
    result = calculate_all(
        {
            "tax_year": 2025,
            "filing_status": "single",
            "salary1_gross": 50000 / 26,
            "salary1_frequency": "biweekly",
            "income_1099nec": 40000,
        }
    )

    fed = result["federal"]
    se = fed["se_tax"]
    # SE earnings = 40000 * 0.9235 = 36940
    # SS portion: 36940 * 0.124 = 4580.56 (under wage base)
    # Medicare: 36940 * 0.029 = 1071.26
    # Total SE: 5651.82
    assert _approx(se["total"], 5651.82, 0.10)
    # 50% of SE tax is deductible
    assert _approx(se["deduction"], 2825.91, 0.10)
    # gross = 90000, agi = 90000 - 2825.91 = 87174.09
    assert _approx(fed["agi"], 87174.09, 0.10)


def test_california_tax_single_w2_2025():
    """CA tax for single filer, $80k W-2."""
    result = calculate_all(
        {
            "tax_year": 2025,
            "filing_status": "single",
            "salary1_gross": 80000 / 26,
            "salary1_frequency": "biweekly",
        }
    )

    ca = result["california"]
    assert ca["standard_deduction"] == 5540
    # CA SDI: 80000 * 0.012 = 960 (under wage base)
    assert _approx(ca["sdi"]["tax"], 960.00, 0.10)
    # CA exemption credit single 2025
    assert ca["exemption_credit"] == 144


def test_high_income_with_itemized_and_salt_cap_2025():
    """Single $300k W-2 with $20k SALT — federal SALT cap should apply."""
    result = calculate_all(
        {
            "tax_year": 2025,
            "filing_status": "single",
            "salary1_gross": 300000 / 26,
            "salary1_frequency": "biweekly",
            "itemized_deductions": {"salt": 20000, "mortgage_interest": 12000},
        }
    )

    fed = result["federal"]
    # SALT capped at 10000 for federal; total itemized = 10000 + 12000 = 22000
    # vs standard 15000 → use itemized
    assert fed["use_itemized"] is True
    assert fed["itemized_deduction"]["breakdown"]["salt"] == 10000
    assert fed["itemized_deduction"]["breakdown"]["salt_capped"] is True


def test_quarterly_guidance_present_for_1099_income_2025():
    """Quarterly guidance must surface when 1099 income exists."""
    result = calculate_all(
        {
            "tax_year": 2025,
            "filing_status": "single",
            "salary1_gross": 50000 / 26,
            "salary1_frequency": "biweekly",
            "income_1099nec": 30000,
        }
    )

    quarterly = result["withholding"]["quarterly_guidance"]
    assert quarterly is not None
    assert len(quarterly["due_dates"]) == 4


def test_calculation_for_2026():
    """Same MFJ scenario but for 2026 — uses 2026 brackets/deductions."""
    result = calculate_all(
        {
            "tax_year": 2026,
            "filing_status": "married_jointly",
            "salary1_gross": 100000 / 26,
            "salary1_frequency": "biweekly",
        }
    )

    fed = result["federal"]
    assert fed["standard_deduction"] == 30800  # 2026 MFJ
    ca = result["california"]
    assert ca["standard_deduction"] == 11360  # 2026 MFJ
