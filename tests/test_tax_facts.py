from decimal import Decimal
from pathlib import Path

import pytest

from app.tax_facts import (
    FactsError,
    FieldError,
    PretaxDeductions,
    SalaryFacts,
    TaxFacts,
    build_facts,
)
from app.tax_registry import FilesystemSource, TaxTableRegistry

DATA_ROOT = Path(__file__).parent.parent / "data" / "tax_tables"


@pytest.fixture(scope="module")
def registry() -> TaxTableRegistry:
    return TaxTableRegistry(source=FilesystemSource(DATA_ROOT))


def _minimal_payload() -> dict:
    return {
        "tax_year": 2025,
        "filing_status": "single",
        "salary1_gross": 2000,
        "salary1_frequency": "biweekly",
    }


def test_build_facts_returns_tax_facts_for_minimal_payload(registry):
    facts = build_facts(_minimal_payload(), tax_tables=registry)

    assert isinstance(facts, TaxFacts)
    assert facts.tax_year == 2025
    assert facts.filing_status == "single"
    assert facts.state == "CA"  # default
    assert facts.salary1.annual == Decimal("52000")  # 2000 * 26
    assert facts.salary2 is None


def test_missing_required_field_raises_facts_error_with_field_path(registry):
    payload = {
        "tax_year": 2025,
        "filing_status": "single",
        # missing salary1_gross and salary1_frequency
    }

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    fields = {e.field: e for e in exc_info.value.errors}
    assert "salary1_gross" in fields
    assert fields["salary1_gross"].code == "missing"
    assert "salary1_frequency" in fields
    assert fields["salary1_frequency"].code == "missing"


def test_bad_numeric_string_raises_type_error(registry):
    payload = _minimal_payload()
    payload["salary1_gross"] = "banana"

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    fields = {e.field: e for e in exc_info.value.errors}
    assert fields["salary1_gross"].code == "type"


def test_bad_int_raises_type_error(registry):
    payload = _minimal_payload()
    payload["tax_year"] = "not-a-year"

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    fields = {e.field: e for e in exc_info.value.errors}
    assert fields["tax_year"].code == "type"


def test_unknown_tax_year_surfaces_available_years(registry):
    payload = _minimal_payload()
    payload["tax_year"] = 2099

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    err = {e.field: e for e in exc_info.value.errors}["tax_year"]
    assert err.code == "unknown_year"
    assert err.detail["available"] == [2025, 2026]


def test_unknown_filing_status_raises(registry):
    payload = _minimal_payload()
    payload["filing_status"] = "wizard"

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    err = {e.field: e for e in exc_info.value.errors}["filing_status"]
    assert err.code == "unknown_filing_status"


def test_unknown_frequency_raises(registry):
    payload = _minimal_payload()
    payload["salary1_frequency"] = "fortnightly"

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    err = {e.field: e for e in exc_info.value.errors}["salary1_frequency"]
    assert err.code == "unknown_frequency"


def test_unknown_state_raises(registry):
    payload = _minimal_payload()
    payload["state"] = "ZZ"

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    err = {e.field: e for e in exc_info.value.errors}["state"]
    assert err.code == "unknown_state"


def test_known_no_tax_state_is_accepted(registry):
    payload = _minimal_payload()
    payload["state"] = "TX"

    facts = build_facts(payload, tax_tables=registry)

    assert facts.state == "TX"


def test_negative_money_is_rejected(registry):
    payload = _minimal_payload()
    payload["salary1_gross"] = -100

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    err = {e.field: e for e in exc_info.value.errors}["salary1_gross"]
    assert err.code == "range"


def test_multiple_errors_collected_in_one_pass(registry):
    payload = {
        "tax_year": 2099,           # unknown_year
        "filing_status": "wizard",   # unknown_filing_status
        "salary1_gross": -50,        # range
        "salary1_frequency": "fortnightly",  # unknown_frequency
        "state": "ZZ",               # unknown_state
    }

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    codes = {e.code for e in exc_info.value.errors}
    assert codes >= {"unknown_year", "unknown_filing_status", "range", "unknown_frequency", "unknown_state"}


def test_dual_income_populates_salary2(registry):
    payload = _minimal_payload()
    payload["dual_income"] = True
    payload["salary2_gross"] = 1500
    payload["salary2_frequency"] = "biweekly"

    facts = build_facts(payload, tax_tables=registry)

    assert facts.salary2 is not None
    assert facts.salary2.annual == Decimal("39000")
    assert facts.dual_income is True


def test_dual_income_true_with_zero_salary2_is_cross_field_error(registry):
    payload = _minimal_payload()
    payload["dual_income"] = True
    payload["salary2_gross"] = 0
    payload["salary2_frequency"] = "biweekly"

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    err = {e.field: e for e in exc_info.value.errors}["salary2_gross"]
    assert err.code == "range"


def test_pretax_per_period_annualizes_with_matching_frequency(registry):
    payload = _minimal_payload()
    payload["pretax_deductions_1"] = {
        "input_type": "per_period",
        "_401k": 500,            # 500 * 26 = 13000
        "health_insurance": 100, # 100 * 26 = 2600
    }

    facts = build_facts(payload, tax_tables=registry)

    assert facts.salary1.pretax._401k == Decimal("13000")
    assert facts.salary1.pretax.health_insurance == Decimal("2600")
    # Untouched fields default to 0
    assert facts.salary1.pretax.hsa == Decimal("0")


def test_pretax_annual_passes_through(registry):
    payload = _minimal_payload()
    payload["pretax_deductions_1"] = {
        "input_type": "annual",
        "_401k": 23500,
    }

    facts = build_facts(payload, tax_tables=registry)

    assert facts.salary1.pretax._401k == Decimal("23500")


def test_1099_and_itemized_default_to_zero(registry):
    facts = build_facts(_minimal_payload(), tax_tables=registry)

    assert facts.income_1099g == Decimal("0")
    assert facts.income_1099nec == Decimal("0")
    assert facts.itemized.total == Decimal("0")


def test_itemized_amounts_sum(registry):
    payload = _minimal_payload()
    payload["itemized_deductions"] = {
        "salt": 12000,
        "mortgage_interest": 8000,
    }

    facts = build_facts(payload, tax_tables=registry)

    assert facts.itemized.salt == Decimal("12000")
    assert facts.itemized.mortgage_interest == Decimal("8000")
    assert facts.itemized.total == Decimal("20000")


def test_401k_over_cap_rejected_with_cap_in_detail(registry):
    payload = _minimal_payload()
    payload["pretax_deductions_1"] = {
        "input_type": "annual",
        "_401k": 50000,  # 2025 cap is 23500
    }

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    err = next(e for e in exc_info.value.errors if "_401k" in e.field)
    assert err.code == "cap_exceeded"
    assert err.detail["cap"] == Decimal("23500")
    assert err.detail["year"] == 2025


def test_dual_income_each_401k_independently_capped(registry):
    """401k cap is per-person — each W-2 can max out separately."""
    payload = _minimal_payload()
    payload["dual_income"] = True
    payload["salary2_gross"] = 1500
    payload["salary2_frequency"] = "biweekly"
    payload["pretax_deductions_1"] = {"input_type": "annual", "_401k": 23500}
    payload["pretax_deductions_2"] = {"input_type": "annual", "_401k": 23500}

    facts = build_facts(payload, tax_tables=registry)

    assert facts.salary1.pretax._401k == Decimal("23500")
    assert facts.salary2.pretax._401k == Decimal("23500")


def test_dual_income_one_salary_over_401k_cap_fails(registry):
    payload = _minimal_payload()
    payload["dual_income"] = True
    payload["salary2_gross"] = 1500
    payload["salary2_frequency"] = "biweekly"
    payload["pretax_deductions_1"] = {"input_type": "annual", "_401k": 23500}
    payload["pretax_deductions_2"] = {"input_type": "annual", "_401k": 30000}  # over cap

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    err = next(e for e in exc_info.value.errors if "_401k" in e.field)
    assert err.code == "cap_exceeded"
    assert err.field == "pretax_deductions_2._401k"


def test_hsa_over_cap_rejected(registry):
    payload = _minimal_payload()
    payload["pretax_deductions_1"] = {"input_type": "annual", "hsa": 20000}  # cap 8550

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    err = next(e for e in exc_info.value.errors if "hsa" in e.field)
    assert err.code == "cap_exceeded"


def test_ira_over_cap_rejected(registry):
    payload = _minimal_payload()
    payload["pretax_deductions_1"] = {"input_type": "annual", "ira": 15000}  # cap 7000

    with pytest.raises(FactsError) as exc_info:
        build_facts(payload, tax_tables=registry)

    err = next(e for e in exc_info.value.errors if "ira" in e.field)
    assert err.code == "cap_exceeded"


def test_under_caps_passes(registry):
    payload = _minimal_payload()
    payload["pretax_deductions_1"] = {
        "input_type": "annual",
        "_401k": 23500,
        "hsa": 8550,
        "ira": 7000,
    }

    facts = build_facts(payload, tax_tables=registry)

    assert facts.salary1.pretax._401k == Decimal("23500")
    assert facts.salary1.pretax.hsa == Decimal("8550")


def test_collect_errors_returns_facts_and_empty_tuple_on_valid(registry):
    facts, errors = TaxFacts.collect_errors(_minimal_payload(), tax_tables=registry)

    assert facts is not None
    assert errors == ()


def test_collect_errors_returns_none_and_errors_on_invalid(registry):
    payload = {"tax_year": "banana", "filing_status": "wizard"}

    facts, errors = TaxFacts.collect_errors(payload, tax_tables=registry)

    assert facts is None
    assert len(errors) > 0
    codes = {e.code for e in errors}
    assert "type" in codes  # tax_year
    assert "unknown_filing_status" in codes


def test_to_state_input_produces_state_tax_input(registry):
    from app.state_tax import StateTaxInput

    payload = _minimal_payload()
    payload["children_under_17"] = 2
    payload["other_dependents"] = 1
    facts = build_facts(payload, tax_tables=registry)

    state_input = facts.to_state_input(
        federal_agi=Decimal("80000"),
        federal_taxable_income=Decimal("65000"),
        federal_itemized=Decimal("0"),
    )

    assert isinstance(state_input, StateTaxInput)
    assert state_input.jurisdiction == facts.state
    assert state_input.year == facts.tax_year
    assert state_input.filing_status == facts.filing_status
    assert state_input.dependents == 3
    assert state_input.federal_agi == Decimal("80000")
    assert state_input.wages_w2 == facts.total_w2_wages
