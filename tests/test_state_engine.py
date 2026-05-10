from decimal import Decimal

import pytest

from pathlib import Path

from app.state_tax import (
    NullStateEngine,
    StandardStateEngine,
    StateEngineRegistry,
    StateTaxInput,
    UnsupportedJurisdiction,
)
from app.state_tax.states.california import CaliforniaEngine
from app.tax_registry import FilesystemSource, InMemorySource, TaxTableRegistry

DATA_ROOT = Path(__file__).parent.parent / "data" / "tax_tables"


def _input(jurisdiction="TX") -> StateTaxInput:
    return StateTaxInput(
        jurisdiction=jurisdiction,
        year=2025,
        filing_status="single",
        dependents=0,
        federal_agi=Decimal("80000"),
        federal_taxable_income=Decimal("65000"),
        federal_itemized=Decimal("0"),
        wages_w2=Decimal("80000"),
        self_employment_income=Decimal("0"),
    )


def test_null_state_engine_returns_zeroed_result():
    engine = NullStateEngine("TX")
    result = engine.compute(_input("TX"))

    assert result.jurisdiction == "TX"
    assert result.taxable_income == Decimal("0")
    assert result.tax_before_credits == Decimal("0")
    assert result.final_tax == Decimal("0")
    assert result.credits == {}
    assert result.addons == {}


@pytest.fixture
def ia_progressive_registry() -> TaxTableRegistry:
    """A typical progressive state. Iowa-shaped: federal_agi start, allows itemized."""
    return TaxTableRegistry(
        source=InMemorySource(
            {
                ("IA", 2025): {
                    "kind": "progressive",
                    "starting_point": "federal_agi",
                    "allows_itemized": True,
                    "filing_statuses": {
                        "single": {
                            "brackets": [
                                {"floor": "0", "rate": "0.044"},
                                {"floor": "6210", "rate": "0.0482"},
                                {"floor": "31230", "rate": "0.057"},
                            ],
                            "standard_deduction": "2210",
                            "dependent_credit": "40",
                        }
                    },
                }
            }
        )
    )


def test_standard_engine_progressive_end_to_end(ia_progressive_registry):
    engine = StandardStateEngine("IA", ia_progressive_registry)
    inp = StateTaxInput(
        jurisdiction="IA",
        year=2025,
        filing_status="single",
        dependents=0,
        federal_agi=Decimal("80000"),
        federal_taxable_income=Decimal("65000"),
        federal_itemized=Decimal("0"),
        wages_w2=Decimal("80000"),
        self_employment_income=Decimal("0"),
    )

    result = engine.compute(inp)

    # Starts from federal AGI (80000)
    assert result.starting_income == Decimal("80000")
    assert result.standard_deduction == Decimal("2210")
    # No itemized, so standard wins
    assert result.use_itemized is False
    assert result.deduction_used == Decimal("2210")
    # Taxable = 80000 - 2210 = 77790
    assert result.taxable_income == Decimal("77790")
    # Tax = 4.4%*6210 + 4.82%*(31230-6210) + 5.7%*(77790-31230)
    #     = 273.240 + 1205.964 + 2653.920 = 4133.124
    assert result.tax_before_credits == Decimal("4133.124")
    # No dependents → no dependent credit applied
    assert result.credits == {}
    assert result.addons == {}
    assert result.final_tax == Decimal("4133.124")


def test_standard_engine_uses_itemized_when_greater(ia_progressive_registry):
    engine = StandardStateEngine("IA", ia_progressive_registry)
    inp = StateTaxInput(
        jurisdiction="IA",
        year=2025,
        filing_status="single",
        dependents=0,
        federal_agi=Decimal("80000"),
        federal_taxable_income=Decimal("65000"),
        federal_itemized=Decimal("12000"),  # > 2210 standard
        wages_w2=Decimal("80000"),
        self_employment_income=Decimal("0"),
    )

    result = engine.compute(inp)

    assert result.use_itemized is True
    assert result.deduction_used == Decimal("12000")
    assert result.taxable_income == Decimal("68000")


def test_standard_engine_uses_standard_when_itemized_smaller(ia_progressive_registry):
    engine = StandardStateEngine("IA", ia_progressive_registry)
    inp = StateTaxInput(
        jurisdiction="IA",
        year=2025,
        filing_status="single",
        dependents=0,
        federal_agi=Decimal("80000"),
        federal_taxable_income=Decimal("65000"),
        federal_itemized=Decimal("1500"),  # < 2210 standard
        wages_w2=Decimal("80000"),
        self_employment_income=Decimal("0"),
    )

    result = engine.compute(inp)

    assert result.use_itemized is False
    assert result.deduction_used == Decimal("2210")


def test_standard_engine_disallows_itemized_when_state_says_so():
    """States like NJ/IL/MA don't allow itemized at all."""
    registry = TaxTableRegistry(
        source=InMemorySource(
            {
                ("NJ", 2025): {
                    "kind": "progressive",
                    "starting_point": "federal_agi",
                    "allows_itemized": False,
                    "filing_statuses": {
                        "single": {
                            "brackets": [{"floor": "0", "rate": "0.05"}],
                            "standard_deduction": "1000",
                            "dependent_credit": "0",
                        }
                    },
                }
            }
        )
    )
    engine = StandardStateEngine("NJ", registry)
    inp = StateTaxInput(
        jurisdiction="NJ",
        year=2025,
        filing_status="single",
        dependents=0,
        federal_agi=Decimal("80000"),
        federal_taxable_income=Decimal("65000"),
        federal_itemized=Decimal("50000"),  # huge but ignored
        wages_w2=Decimal("80000"),
        self_employment_income=Decimal("0"),
    )

    result = engine.compute(inp)

    assert result.use_itemized is False
    assert result.deduction_used == Decimal("1000")
    assert result.itemized_deduction == Decimal("0")


def test_standard_engine_starts_from_federal_taxable_income_when_configured():
    """Colorado-style: starting_point=federal_taxable, flat tax."""
    registry = TaxTableRegistry(
        source=InMemorySource(
            {
                ("CO", 2025): {
                    "kind": "progressive",
                    "starting_point": "federal_taxable",
                    "allows_itemized": False,
                    "filing_statuses": {
                        "single": {
                            "brackets": [{"floor": "0", "rate": "0.044"}],
                            "standard_deduction": "0",
                            "dependent_credit": "0",
                        }
                    },
                }
            }
        )
    )
    engine = StandardStateEngine("CO", registry)
    inp = StateTaxInput(
        jurisdiction="CO",
        year=2025,
        filing_status="single",
        dependents=0,
        federal_agi=Decimal("80000"),
        federal_taxable_income=Decimal("65000"),  # the one that matters
        federal_itemized=Decimal("0"),
        wages_w2=Decimal("80000"),
        self_employment_income=Decimal("0"),
    )

    result = engine.compute(inp)

    assert result.starting_income == Decimal("65000")
    # 65000 * 4.4% = 2860
    assert result.tax_before_credits == Decimal("2860.000")
    assert result.final_tax == Decimal("2860.000")


def test_subclass_overrides_addons_and_inherits_pipeline(ia_progressive_registry):
    """A state engine override should be able to add addons without reimplementing
    the deduction/bracket pipeline. Final tax = tax - credits + addons."""

    class FakeOutlierEngine(StandardStateEngine):
        def compute_addons(self, inp, profile, taxable_income):
            return {"fake_disability_premium": Decimal("123.45")}

    engine = FakeOutlierEngine("IA", ia_progressive_registry)
    inp = StateTaxInput(
        jurisdiction="IA",
        year=2025,
        filing_status="single",
        dependents=0,
        federal_agi=Decimal("80000"),
        federal_taxable_income=Decimal("65000"),
        federal_itemized=Decimal("0"),
        wages_w2=Decimal("80000"),
        self_employment_income=Decimal("0"),
    )

    result = engine.compute(inp)

    # Same bracket math as test_standard_engine_progressive_end_to_end
    assert result.tax_before_credits == Decimal("4133.124")
    assert result.addons == {"fake_disability_premium": Decimal("123.45")}
    # Addons are payroll-side and NOT part of final_tax (income tax only)
    assert result.final_tax == Decimal("4133.124")


def test_subclass_overrides_surcharges_and_adds_to_final(ia_progressive_registry):
    class FakeSurchargeEngine(StandardStateEngine):
        def compute_surcharges(self, inp, profile, taxable_income):
            return {"fake_high_earner_surcharge": Decimal("250")}

    engine = FakeSurchargeEngine("IA", ia_progressive_registry)
    inp = StateTaxInput(
        jurisdiction="IA",
        year=2025,
        filing_status="single",
        dependents=0,
        federal_agi=Decimal("80000"),
        federal_taxable_income=Decimal("65000"),
        federal_itemized=Decimal("0"),
        wages_w2=Decimal("80000"),
        self_employment_income=Decimal("0"),
    )

    result = engine.compute(inp)

    # Surcharges ARE part of final_tax: 4133.124 + 250 = 4383.124
    assert result.surcharges == {"fake_high_earner_surcharge": Decimal("250")}
    assert result.final_tax == Decimal("4383.124")


def test_subclass_overrides_credits_and_subtracts_from_final(ia_progressive_registry):
    class FakeCreditEngine(StandardStateEngine):
        def compute_credits(self, inp, profile, taxable_income):
            return {"fake_renter_credit": Decimal("100")}

    engine = FakeCreditEngine("IA", ia_progressive_registry)
    inp = StateTaxInput(
        jurisdiction="IA",
        year=2025,
        filing_status="single",
        dependents=0,
        federal_agi=Decimal("80000"),
        federal_taxable_income=Decimal("65000"),
        federal_itemized=Decimal("0"),
        wages_w2=Decimal("80000"),
        self_employment_income=Decimal("0"),
    )

    result = engine.compute(inp)

    # tax 4133.124 - credit 100 = 4033.124
    assert result.credits == {"fake_renter_credit": Decimal("100")}
    assert result.final_tax == Decimal("4033.124")


def test_registry_returns_null_engine_for_no_tax_state():
    tables = TaxTableRegistry(source=InMemorySource({}))
    engines = StateEngineRegistry(registry=tables)

    assert isinstance(engines.get("TX"), NullStateEngine)
    assert isinstance(engines.get("FL"), NullStateEngine)


def test_registry_returns_standard_engine_for_jurisdiction_with_table(
    ia_progressive_registry,
):
    engines = StateEngineRegistry(registry=ia_progressive_registry)

    engine = engines.get("IA")

    assert isinstance(engine, StandardStateEngine)
    assert engine.jurisdiction == "IA"


def test_registry_returns_registered_override_class(ia_progressive_registry):
    class CustomEngine(StandardStateEngine):
        pass

    engines = StateEngineRegistry(registry=ia_progressive_registry)
    engines.register("IA", CustomEngine)

    engine = engines.get("IA")

    assert isinstance(engine, CustomEngine)
    assert engine.jurisdiction == "IA"


def test_registry_raises_for_unknown_jurisdiction():
    tables = TaxTableRegistry(source=InMemorySource({}))
    engines = StateEngineRegistry(registry=tables)

    with pytest.raises(UnsupportedJurisdiction) as exc_info:
        engines.get("XX")

    assert exc_info.value.jurisdiction == "XX"


@pytest.fixture(scope="module")
def real_registry() -> TaxTableRegistry:
    return TaxTableRegistry(source=FilesystemSource(DATA_ROOT))


def test_california_engine_addons_match_legacy_for_2025_single(real_registry):
    """CA SDI on $80k W-2 should be 80000 * 0.012 = 960 (under wage base)."""
    engine = CaliforniaEngine("CA", real_registry)
    inp = StateTaxInput(
        jurisdiction="CA",
        year=2025,
        filing_status="single",
        dependents=0,
        federal_agi=Decimal("80000"),
        federal_taxable_income=Decimal("65000"),
        federal_itemized=Decimal("0"),
        wages_w2=Decimal("80000"),
        self_employment_income=Decimal("0"),
    )

    result = engine.compute(inp)

    assert result.addons["sdi"] == Decimal("960.000")
    # Mental Health Tax: CA taxable 80000-5540=74460 < 1M → zero
    assert result.surcharges["mhst"] == Decimal("0")


def test_california_engine_credits_match_legacy_for_2025_single(real_registry):
    engine = CaliforniaEngine("CA", real_registry)
    inp = StateTaxInput(
        jurisdiction="CA",
        year=2025,
        filing_status="single",
        dependents=2,  # 2 dependents → 2 * 446 = 892 dependent credit
        federal_agi=Decimal("80000"),
        federal_taxable_income=Decimal("65000"),
        federal_itemized=Decimal("0"),
        wages_w2=Decimal("80000"),
        self_employment_income=Decimal("0"),
    )

    result = engine.compute(inp)

    assert result.credits["exemption"] == Decimal("144")
    assert result.credits["dependent"] == Decimal("892")


def test_california_engine_mhst_kicks_in_above_1m_ca_taxable(real_registry):
    """MHST is computed on CA's *own* taxable income, not federal."""
    engine = CaliforniaEngine("CA", real_registry)
    inp = StateTaxInput(
        jurisdiction="CA",
        year=2025,
        filing_status="single",
        dependents=0,
        federal_agi=Decimal("1500000"),
        federal_taxable_income=Decimal("1200000"),
        federal_itemized=Decimal("0"),
        wages_w2=Decimal("250000"),
        self_employment_income=Decimal("0"),
    )

    result = engine.compute(inp)

    # CA AGI = federal_agi = 1500000
    # CA taxable = 1500000 - 5540 (CA single std) = 1494460
    # MHST = (1494460 - 1000000) * 0.01 = 4944.60
    assert result.taxable_income == Decimal("1494460")
    assert result.surcharges["mhst"] == Decimal("4944.60")
