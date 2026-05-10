from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class StateTaxInput:
    jurisdiction: str
    year: int
    filing_status: str
    dependents: int
    federal_agi: Decimal
    federal_taxable_income: Decimal
    federal_itemized: Decimal
    wages_w2: Decimal
    self_employment_income: Decimal
    state_facts: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StateTaxResult:
    jurisdiction: str
    starting_income: Decimal = Decimal("0")
    standard_deduction: Decimal = Decimal("0")
    itemized_deduction: Decimal = Decimal("0")
    use_itemized: bool = False
    deduction_used: Decimal = Decimal("0")
    taxable_income: Decimal = Decimal("0")
    tax_before_credits: Decimal = Decimal("0")
    bracket_breakdown: tuple = ()
    credits: Mapping[str, Decimal] = field(default_factory=dict)
    surcharges: Mapping[str, Decimal] = field(default_factory=dict)  # added to final_tax
    addons: Mapping[str, Decimal] = field(default_factory=dict)      # NOT in final_tax
    final_tax: Decimal = Decimal("0")
    extras: Mapping[str, Any] = field(default_factory=dict)
