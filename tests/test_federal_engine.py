"""
Boundary tests for FederalEngine — Decimal-native, exact assertions.

These complement the legacy float-tolerant goldens in test_calculator_golden.py.
They assert directly on the typed FederalResult to verify Decimal precision and
structural invariants the dict shape can't express cleanly.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.federal_tax import FederalEngine, FederalResult
from app.tax_facts import build_facts
from app.tax_registry import FilesystemSource, TaxTableRegistry

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "tax_tables"


@pytest.fixture(scope="module")
def registry() -> TaxTableRegistry:
    return TaxTableRegistry(source=FilesystemSource(DATA_ROOT))


@pytest.fixture(scope="module")
def engine(registry: TaxTableRegistry) -> FederalEngine:
    return FederalEngine(registry)


def _facts(registry, **overrides):
    # Use an exact-divisible salary to keep Decimal arithmetic clean.
    # Default: $78,000 biweekly = $3,000/period exactly.
    payload = {
        "tax_year": 2025,
        "filing_status": "single",
        "salary1_gross": 3000,
        "salary1_frequency": "biweekly",
    }
    payload.update(overrides)
    return build_facts(payload, tax_tables=registry, state_engines=None)


def test_single_w2_only_2025_decimal_exact(engine, registry):
    fed: FederalResult = engine.compute(_facts(registry))

    # $3,000 biweekly × 26 = $78,000 gross. - $15,000 std = $63,000 taxable.
    # 10%×11,925 + 12%×(48,475-11,925) + 22%×(63,000-48,475)
    # = 1,192.50 + 4,386.00 + 3,195.50 = 8,774.00
    assert fed.standard_deduction == Decimal("15000")
    assert fed.taxable_income == Decimal("63000")
    assert fed.tax_before_credits == Decimal("8774.00")
    assert fed.child_tax_credit.amount == Decimal("0")
    assert fed.final_tax == Decimal("8774.00")
    assert fed.use_itemized is False


def test_bracket_breakdown_invariant_holds(engine, registry):
    """Sum of per-bracket taxes must equal tax_before_credits — exact in Decimal."""
    fed = engine.compute(_facts(registry))
    assert sum((b.tax for b in fed.bracket_breakdown), Decimal("0")) == fed.tax_before_credits
    assert sum((b.taxable_amount for b in fed.bracket_breakdown), Decimal("0")) == fed.taxable_income


def test_bracket_breakdown_empty_when_no_taxable_income(engine, registry):
    # $400 biweekly × 26 = $10,400 gross < $15,000 std deduction
    fed = engine.compute(
        _facts(
            registry,
            salary1_gross=400,
            salary1_frequency="biweekly",
        )
    )
    assert fed.taxable_income == Decimal("0")
    assert fed.bracket_breakdown == ()
    assert fed.tax_before_credits == Decimal("0")


def test_se_tax_components_sum_to_total(engine, registry):
    # $1,923.08 × 26 ≈ $50k — value not asserted; only SE tax math is.
    fed = engine.compute(
        _facts(
            registry,
            salary1_gross=2000,
            salary1_frequency="biweekly",
            income_1099nec=40000,
        )
    )
    se = fed.se_tax
    assert se.ss_tax + se.medicare_tax == se.total
    assert se.deduction == se.total / 2
    assert se.se_income == Decimal("40000") * Decimal("0.9235")


def test_no_se_tax_when_no_1099nec(engine, registry):
    fed = engine.compute(_facts(registry))
    assert fed.se_tax.total == Decimal("0")
    assert fed.se_tax.deduction == Decimal("0")


def test_salt_cap_applied_at_federal_boundary(engine, registry):
    fed = engine.compute(
        _facts(
            registry,
            salary1_gross=11538.46,
            salary1_frequency="biweekly",
            itemized_deductions={"salt": 20000, "mortgage_interest": 12000},
        )
    )
    assert fed.itemized.salt == Decimal("10000")
    assert fed.itemized.salt_capped is True
    assert fed.itemized.salt_original == Decimal("20000")
    # Total uses the capped salt, not the original
    assert fed.itemized.total == Decimal("22000")
    assert fed.use_itemized is True
    assert fed.deduction_used == Decimal("22000")


def test_child_tax_credit_full_below_phaseout(engine, registry):
    # $5,000 biweekly × 26 = $130,000 — well below $400k MFJ threshold.
    fed = engine.compute(
        _facts(
            registry,
            filing_status="married_jointly",
            salary1_gross=5000,
            salary1_frequency="biweekly",
            children_under_17=2,
        )
    )
    # 2025 MFJ CTC: 2 × $2,000 = $4,000 full credit
    assert fed.child_tax_credit.amount == Decimal("4000")
    assert fed.child_tax_credit.phased_out == Decimal("0")


def test_child_tax_credit_phases_out_at_high_agi(engine, registry):
    # $11,538.46 biweekly ≈ $300k — well above $200k single threshold.
    fed = engine.compute(
        _facts(
            registry,
            filing_status="single",
            salary1_gross=11538.46,
            salary1_frequency="biweekly",
            children_under_17=1,
        )
    )
    # Single CTC threshold $200k. AGI ~$300k → excess ~$100k → phase-out ~$5k.
    # Base credit $2k → fully phased out.
    assert fed.child_tax_credit.amount == Decimal("0")
    assert fed.child_tax_credit.phased_out == Decimal("2000")


def test_engine_uses_injected_registry_not_a_global(registry):
    """A second engine bound to the same registry must see the same results."""
    e1 = FederalEngine(registry)
    e2 = FederalEngine(registry)
    facts = _facts(registry)
    assert e1.compute(facts) == e2.compute(facts)
