"""
Primary seam for Annual Tax Projection: `TaxPipeline.project(raw_inputs)`.

Expected values are hand-computed from the 2025/2026 tables with the
arithmetic shown in comments.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.state_tax import StateEngineRegistry
from app.state_tax.states import register_overrides
from app.tax_calculator import TaxPipeline
from app.tax_facts import FactsError
from app.tax_registry import FilesystemSource, TaxTableRegistry

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "tax_tables"


@pytest.fixture(scope="module")
def pipeline() -> TaxPipeline:
    registry = TaxTableRegistry(source=FilesystemSource(DATA_ROOT))
    engines = StateEngineRegistry(registry=registry)
    register_overrides(engines)
    return TaxPipeline(registry, engines)


def _quick(**overrides):
    payload = {
        "tax_year": 2025,
        "filing_status": "single",
        "state": "CA",
        "salary1_annual": 78000,
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


def test_annual_salary_matches_equivalent_per_period_input(pipeline):
    annual = pipeline.project(_quick(salary1_annual=78000))
    per_period = pipeline.project(
        _quick(salary1_annual=None, salary1_gross=3000, salary1_frequency="biweekly")
    )

    assert annual.liabilities == per_period.liabilities
    assert annual.total_liability == per_period.total_liability
    assert annual.gross_income == per_period.gross_income == Decimal("78000")


def test_quick_projection_single_2025_ca(pipeline):
    result = pipeline.project(_quick())

    # Federal: 78,000 - 15,000 std = 63,000 taxable
    #   10%×11,925 + 12%×36,550 + 22%×14,525 = 1,192.50 + 4,386.00 + 3,195.50 = 8,774.00
    assert result.liabilities.federal_income_tax == Decimal("8774.00")
    assert result.liabilities.self_employment_tax == Decimal("0")
    # CA: 78,000 - 5,540 std = 72,460 taxable
    #   1%×10,756=107.56  2%×14,743=294.86  4%×14,744=589.76  6%×15,623=937.38
    #   8%×14,740=1,179.20  9.3%×1,854=172.422  → 3,281.182 − 144 exemption = 3,137.182
    assert result.liabilities.state_income_tax == Decimal("3137.182")
    # SDI 2025: 78,000 × 1.2% = 936
    assert result.liabilities.state_sdi == Decimal("936")
    # FICA 2025: SS 78,000 × 6.2% = 4,836; Medicare 78,000 × 1.45% = 1,131
    assert result.liabilities.social_security == Decimal("4836")
    assert result.liabilities.medicare == Decimal("1131")
    # Total 8,774 + 3,137.182 + 936 + 4,836 + 1,131 = 18,814.182; ÷ 78,000
    assert result.total_liability == Decimal("18814.182")
    assert result.effective_rate.quantize(Decimal("0.000001")) == Decimal("0.241207")


def test_quick_projection_mfj_dual_income_2026_ca(pipeline):
    result = pipeline.project(
        _quick(
            tax_year=2026,
            filing_status="married_jointly",
            salary1_annual=150000,
            dual_income=True,
            salary2_annual=190000,
        )
    )

    assert result.gross_income == Decimal("340000")
    # Federal: 340,000 - 30,800 = 309,200 taxable
    #   10%×24,500=2,450  12%×75,150=9,018  22%×112,850=24,827  24%×96,700=23,208
    #   = 59,503
    assert result.liabilities.federal_income_tax == Decimal("59503")
    # CA: 340,000 - 11,360 = 328,640 taxable
    #   1%×22,050=220.50  2%×30,223=604.46  4%×30,225=1,209  6%×32,028=1,921.68
    #   8%×30,216=2,417.28  9.3%×183,898=17,102.514 → 23,475.434 − 296 = 23,179.434
    assert result.liabilities.state_income_tax == Decimal("23179.434")
    # SDI 2026 per employee: 150,000×1.1%=1,650 + min(190,000, 180,000)×1.1%=1,980
    assert result.liabilities.state_sdi == Decimal("3630")
    # FICA 2026: SS 150,000×6.2%=9,300 + 184,500 (capped)×6.2%=11,439 = 20,739
    #   Medicare 340,000×1.45%=4,930 + Additional (340,000−250,000)×0.9%=810 = 5,740
    assert result.liabilities.social_security == Decimal("20739")
    assert result.liabilities.medicare == Decimal("5740")
    # 59,503 + 23,179.434 + 3,630 + 20,739 + 5,740 = 112,791.434; ÷ 340,000
    assert result.total_liability == Decimal("112791.434")
    assert result.effective_rate.quantize(Decimal("0.000001")) == Decimal("0.331740")


def test_no_income_tax_state_has_no_state_lines(pipeline):
    result = pipeline.project(_quick(state="TX"))
    assert result.liabilities.state_income_tax == Decimal("0")
    assert result.liabilities.state_sdi == Decimal("0")
    # 8,774 federal + 4,836 SS + 1,131 Medicare
    assert result.total_liability == Decimal("14741.00")


def test_section_125_deductions_reduce_sdi_wages_but_401k_does_not(pipeline):
    result = pipeline.project(
        _quick(
            pretax_deductions_1={
                "input_type": "annual",
                "_401k": 10000,
                "health_insurance": 3000,
            }
        )
    )
    # SDI wages: 78,000 − 3,000 health (Section 125) = 75,000 × 1.2% = 900
    assert result.liabilities.state_sdi == Decimal("900")


@pytest.mark.parametrize("missing", ["tax_year", "filing_status", "state", "salary1_annual"])
def test_missing_required_field_is_a_validation_error(pipeline, missing):
    payload = _quick()
    del payload[missing]
    with pytest.raises(FactsError) as exc_info:
        pipeline.project(payload)
    fields = {e.field for e in exc_info.value.errors}
    expected = "salary1_gross" if missing == "salary1_annual" else missing
    assert expected in fields


def test_per_paycheck_deductions_without_frequency_are_rejected(pipeline):
    with pytest.raises(FactsError) as exc_info:
        pipeline.project(_quick(pretax_deductions_1={"_401k": 500}))
    codes = {e.code for e in exc_info.value.errors}
    assert "frequency_required" in codes


# --- Employee FICA (#19) ---------------------------------------------------


def _mfj_2026(**overrides):
    return _quick(
        tax_year=2026,
        filing_status="married_jointly",
        salary1_annual=150000,
        dual_income=True,
        salary2_annual=190000,
        **overrides,
    )


def test_social_security_is_capped_per_salary(pipeline):
    result = pipeline.project(_mfj_2026())
    # 2026 SS wage base 184,500 @ 6.2%:
    #   salary1 150,000 (below cap) × 6.2% = 9,300
    #   salary2 190,000 → capped 184,500 × 6.2% = 11,439
    assert result.fica.salary1_social_security == Decimal("9300")
    assert result.fica.salary2_social_security == Decimal("11439")
    assert result.liabilities.social_security == Decimal("20739")


def test_additional_medicare_uses_household_threshold_by_filing_status(pipeline):
    single = pipeline.project(_quick(salary1_annual=260000))
    # Single threshold 200,000: (260,000 − 200,000) × 0.9% = 540
    #   regular 260,000 × 1.45% = 3,770 → Medicare line 4,310
    assert single.fica.additional_medicare == Decimal("540")
    assert single.liabilities.medicare == Decimal("4310")

    mfj = pipeline.project(
        _quick(
            filing_status="married_jointly",
            salary1_annual=130000,
            dual_income=True,
            salary2_annual=130000,
        )
    )
    # MFJ threshold 250,000 on combined wages: (260,000 − 250,000) × 0.9% = 90
    #   (neither spouse alone is over 200,000)
    assert mfj.fica.additional_medicare == Decimal("90")
    assert mfj.liabilities.medicare == Decimal("3860")


def test_section_125_reduces_fica_wages_but_401k_does_not(pipeline):
    result = pipeline.project(
        _quick(
            pretax_deductions_1={
                "input_type": "annual",
                "_401k": 10000,
                "ira": 2000,
                "health_insurance": 3000,
                "dental": 500,
                "vision": 200,
                "fsa": 1000,
                "hsa": 1300,
            }
        )
    )
    # FICA wages: 78,000 − (3,000 + 500 + 200 + 1,000 + 1,300) = 72,000
    #   401(k) and IRA are ignored.
    assert result.fica.salary1_fica_wages == Decimal("72000")
    # SS 72,000 × 6.2% = 4,464; Medicare 72,000 × 1.45% = 1,044
    assert result.liabilities.social_security == Decimal("4464")
    assert result.liabilities.medicare == Decimal("1044")


def test_social_security_wage_base_comes_from_the_year_table(pipeline):
    y2025 = pipeline.project(_quick(salary1_annual=180000, state="TX"))
    y2026 = pipeline.project(_quick(tax_year=2026, salary1_annual=180000, state="TX"))
    # 2025 base 176,100 × 6.2% = 10,918.20 (capped)
    assert y2025.liabilities.social_security == Decimal("10918.2")
    # 2026 base 184,500 > 180,000 → 180,000 × 6.2% = 11,160 (uncapped)
    assert y2026.liabilities.social_security == Decimal("11160")

# --- Refinement inputs (#20) -------------------------------------------------


def test_per_paycheck_pretax_with_frequency_annualizes(pipeline):
    result = pipeline.project(
        _quick(salary1_frequency="biweekly", pretax_deductions_1={"_401k": 500})
    )
    # 401(k): 500 × 26 = 13,000. Federal: 78,000 − 13,000 − 15,000 = 50,000 taxable
    #   1,192.50 + 4,386.00 + 22%×1,525 = 335.50 → 5,914.00
    assert result.liabilities.federal_income_tax == Decimal("5914.00")
    # 401(k) does not reduce SDI wages: 78,000 × 1.2% = 936
    assert result.liabilities.state_sdi == Decimal("936")


def test_1099_nec_income_adds_self_employment_tax_line(pipeline):
    result = pipeline.project(_quick(income_1099nec=20000))

    assert result.gross_income == Decimal("98000")
    # SE income 20,000 × 0.9235 = 18,470
    #   SS 12.4% = 2,290.28; Medicare 2.9% = 535.63 → 2,825.91
    assert result.liabilities.self_employment_tax == Decimal("2825.91")
    # AGI 98,000 − ½SE 1,412.955 = 96,587.045; − 15,000 std = 81,587.045 taxable
    #   1,192.50 + 4,386.00 + 22%×33,112.045 = 7,284.6499 → 12,863.1499
    assert result.liabilities.federal_income_tax == Decimal("12863.1499")
    # CA from federal AGI: 96,587.045 − 5,540 = 91,047.045 taxable
    #   3,108.76 through 8% + 9.3%×20,441.045 = 1,901.017185 → 5,009.777185 − 144
    assert result.liabilities.state_income_tax == Decimal("4865.777185")
    # SDI applies to W-2 wages only: 78,000 × 1.2% = 936
    assert result.liabilities.state_sdi == Decimal("936")
    # FICA on W-2 wages: SS 78,000 × 6.2% = 4,836; Medicare 78,000 × 1.45% = 1,131
    # 12,863.1499 + 2,825.91 + 4,865.777185 + 936 + 4,836 + 1,131
    assert result.total_liability == Decimal("27457.837085")


def test_children_reduce_federal_and_state_tax_through_credits(pipeline):
    result = pipeline.project(_quick(children_under_17=2))
    # Federal CTC 2 × 2,000 = 4,000: 8,774 − 4,000 = 4,774
    assert result.liabilities.federal_income_tax == Decimal("4774.00")
    # CA dependent credit 2 × 446 = 892: 3,137.182 − 892 = 2,245.182
    assert result.liabilities.state_income_tax == Decimal("2245.182")


def test_itemized_deductions_above_standard_are_used(pipeline):
    result = pipeline.project(
        _quick(itemized_deductions={"mortgage_interest": 20000, "charitable": 5000})
    )
    # Itemized 25,000 > 15,000 std: 78,000 − 25,000 = 53,000 taxable
    #   1,192.50 + 4,386.00 + 22%×4,525 = 995.50 → 6,574.00
    assert result.liabilities.federal_income_tax == Decimal("6574.00")


def test_itemized_deductions_below_standard_fall_back_to_standard(pipeline):
    result = pipeline.project(_quick(itemized_deductions={"charitable": 5000}))
    assert result.liabilities.federal_income_tax == Decimal("8774.00")


def test_student_loan_interest_reduces_federal_tax(pipeline):
    result = pipeline.project(_quick(student_loan_interest=2000))
    # AGI 76,000 − 15,000 = 61,000 taxable: 8,774 − 22%×2,000 = 8,334
    assert result.liabilities.federal_income_tax == Decimal("8334.00")


def test_other_1099_income_is_taxed_without_self_employment_tax(pipeline):
    result = pipeline.project(
        _quick(income_1099g=1000, income_1099int_div=500, other_income=500)
    )
    assert result.gross_income == Decimal("80000")
    assert result.liabilities.self_employment_tax == Decimal("0")
    # 65,000 taxable: 8,774 + 22%×2,000 = 9,214
    assert result.liabilities.federal_income_tax == Decimal("9214.00")


# --- Marginal rates and take-home (#21) -------------------------------------


def test_marginal_rates_come_from_the_bracket_containing_taxable_income(pipeline):
    # Single 2025 CA, 78,000: federal taxable 63,000 is in the 22% bracket
    # (48,475–103,350); CA taxable 72,460 is in the 9.3% bracket (70,606–360,659).
    result = pipeline.project(_quick())
    assert result.marginal_rates.federal == Decimal("0.22")
    assert result.marginal_rates.state == Decimal("0.093")


def test_mfj_marginal_rates(pipeline):
    # MFJ 2026: federal taxable 309,200 in 24% (212,500–405,650); CA 328,640 in 9.3%.
    result = pipeline.project(_mfj_2026())
    assert result.marginal_rates.federal == Decimal("0.24")
    assert result.marginal_rates.state == Decimal("0.093")


@pytest.mark.parametrize(
    "salary, expected",
    [
        # 63,475 − 15,000 = 48,475: exactly the 22% floor, so the next dollar is 22%
        (63475, Decimal("0.22")),
        # one dollar below the floor: still 12%
        (63474, Decimal("0.12")),
    ],
)
def test_federal_marginal_rate_at_bracket_boundary(pipeline, salary, expected):
    result = pipeline.project(_quick(state="TX", salary1_annual=salary))
    assert result.marginal_rates.federal == expected


def test_state_marginal_rate_at_bracket_boundary(pipeline):
    # 76,146 − 5,540 CA std = 70,606: exactly the 9.3% floor
    result = pipeline.project(_quick(salary1_annual=76146))
    assert result.marginal_rates.state == Decimal("0.093")
    # 76,145 → 70,605: still 8%
    below = pipeline.project(_quick(salary1_annual=76145))
    assert below.marginal_rates.state == Decimal("0.08")


def test_no_income_tax_state_has_zero_state_marginal_rate(pipeline):
    result = pipeline.project(_quick(state="TX"))
    assert result.marginal_rates.state == Decimal("0")


def test_annual_take_home_single(pipeline):
    result = pipeline.project(_quick())
    # 78,000 − 8,774 fed − 3,137.182 CA − 936 SDI − 4,836 SS − 1,131 Medicare
    assert result.take_home.annual == Decimal("59185.818")


def test_annual_take_home_mfj(pipeline):
    result = pipeline.project(_mfj_2026())
    # 340,000 − 59,503 − 23,179.434 − 3,630 − 20,739 − 5,740 = 227,208.566
    assert result.take_home.annual == Decimal("227208.566")


def test_annual_take_home_subtracts_pretax_deductions(pipeline):
    result = pipeline.project(
        _quick(
            state="TX",
            pretax_deductions_1={"input_type": "annual", "_401k": 10000, "health_insurance": 3000},
        )
    )
    # Federal: 78,000 − 13,000 − 15,000 = 50,000 taxable
    #   1,192.50 + 4,386.00 + 22%×1,525=335.50 → 5,914
    # FICA wages 75,000: SS 4,650; Medicare 1,087.50
    # 78,000 − 13,000 − 5,914 − 4,650 − 1,087.50 = 53,348.50
    assert result.take_home.annual == Decimal("53348.50")


def test_per_paycheck_take_home_divides_annual_by_pay_periods(pipeline):
    result = pipeline.project(
        _quick(salary1_annual=None, salary1_gross=3000, salary1_frequency="biweekly")
    )
    # 59,185.818 ÷ 26 = 2,276.3776…
    assert result.take_home.periods_per_year == 26
    assert result.take_home.per_paycheck.quantize(Decimal("0.01")) == Decimal("2276.38")


def test_per_paycheck_take_home_absent_without_frequency(pipeline):
    result = pipeline.project(_quick())
    assert result.take_home.per_paycheck is None
    assert result.take_home.periods_per_year is None
