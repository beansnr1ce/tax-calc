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
    # Total 8,774 + 3,137.182 + 936 = 12,847.182; ÷ 78,000
    assert result.total_liability == Decimal("12847.182")
    assert result.effective_rate.quantize(Decimal("0.000001")) == Decimal("0.164707")


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
    # 59,503 + 23,179.434 + 3,630 = 86,312.434; ÷ 340,000 = 0.2538601
    assert result.total_liability == Decimal("86312.434")
    assert result.effective_rate == Decimal("0.2538601")


def test_no_income_tax_state_has_no_state_lines(pipeline):
    result = pipeline.project(_quick(state="TX"))
    assert result.liabilities.state_income_tax == Decimal("0")
    assert result.liabilities.state_sdi == Decimal("0")
    assert result.total_liability == Decimal("8774.00")


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
