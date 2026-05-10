from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from app.state_tax import StateTaxInput
    from app.tax_registry import TaxTableRegistry


@dataclass(frozen=True)
class PretaxDeductions:
    """All fields are ANNUALIZED Decimal amounts. input_type is consumed and discarded."""
    _401k: Decimal = Decimal("0")
    ira: Decimal = Decimal("0")
    health_insurance: Decimal = Decimal("0")
    hsa: Decimal = Decimal("0")
    fsa: Decimal = Decimal("0")
    dental: Decimal = Decimal("0")
    vision: Decimal = Decimal("0")
    other: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return (
            self._401k
            + self.ira
            + self.health_insurance
            + self.hsa
            + self.fsa
            + self.dental
            + self.vision
            + self.other
        )


@dataclass(frozen=True)
class SalaryFacts:
    gross_per_period: Decimal
    frequency: str
    periods_per_year: int
    annual: Decimal
    pretax: PretaxDeductions


@dataclass(frozen=True)
class ItemizedDeductions:
    charitable: Decimal = Decimal("0")
    mortgage_interest: Decimal = Decimal("0")
    salt: Decimal = Decimal("0")
    medical: Decimal = Decimal("0")
    other: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return (
            self.charitable
            + self.mortgage_interest
            + self.salt
            + self.medical
            + self.other
        )


@dataclass(frozen=True)
class TaxFacts:
    tax_year: int
    filing_status: str
    state: str
    salary1: SalaryFacts
    salary2: SalaryFacts | None
    income_1099g: Decimal = Decimal("0")
    income_1099nec: Decimal = Decimal("0")
    income_1099int_div: Decimal = Decimal("0")
    other_income: Decimal = Decimal("0")
    children_under_17: int = 0
    other_dependents: int = 0
    student_loan_interest: Decimal = Decimal("0")
    itemized: ItemizedDeductions = ItemizedDeductions()

    @property
    def dual_income(self) -> bool:
        return self.salary2 is not None

    @property
    def total_w2_wages(self) -> Decimal:
        return self.salary1.annual + (self.salary2.annual if self.salary2 else Decimal("0"))

    @property
    def total_1099_income(self) -> Decimal:
        return (
            self.income_1099g
            + self.income_1099nec
            + self.income_1099int_div
            + self.other_income
        )

    @property
    def total_pretax(self) -> Decimal:
        return self.salary1.pretax.total + (
            self.salary2.pretax.total if self.salary2 else Decimal("0")
        )

    def to_state_input(
        self,
        *,
        federal_agi: Decimal,
        federal_taxable_income: Decimal,
        federal_itemized: Decimal,
    ) -> "StateTaxInput":
        from app.state_tax import StateTaxInput

        return StateTaxInput(
            jurisdiction=self.state,
            year=self.tax_year,
            filing_status=self.filing_status,
            dependents=self.children_under_17 + self.other_dependents,
            federal_agi=federal_agi,
            federal_taxable_income=federal_taxable_income,
            federal_itemized=federal_itemized,
            wages_w2=self.total_w2_wages,
            self_employment_income=self.income_1099nec,
        )

    @classmethod
    def collect_errors(
        cls,
        payload: Mapping[str, Any],
        *,
        tax_tables: "TaxTableRegistry",
        state_engines=None,
    ) -> tuple["TaxFacts | None", tuple]:
        from .builder import build_facts
        from .errors import FactsError

        try:
            facts = build_facts(payload, tax_tables=tax_tables, state_engines=state_engines)
            return facts, ()
        except FactsError as e:
            return None, e.errors
