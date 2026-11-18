"""Typed result of an Annual Tax Projection.

Frozen dataclasses, Decimal amounts, unrounded. Serialization (rounding,
JSON shape) happens at the HTTP route, not here.

Extension points for later work:
- New liability lines (e.g. Employee FICA) are added as fields on
  `Liabilities`; `Liabilities.total` sums every field, so they count toward
  `total_liability` and the effective rate automatically.
- New result sections (marginal rates, take-home, YTD) are added as
  defaulted fields on `ProjectionResult`.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal

_ZERO = Decimal("0")


@dataclass(frozen=True)
class Liabilities:
    """Projected annual liability per authority. Every field is a Decimal
    amount and part of the total."""

    federal_income_tax: Decimal = _ZERO
    self_employment_tax: Decimal = _ZERO
    state_income_tax: Decimal = _ZERO
    state_sdi: Decimal = _ZERO

    @property
    def total(self) -> Decimal:
        return sum((getattr(self, f.name) for f in fields(self)), _ZERO)

    def items(self) -> tuple[tuple[str, Decimal], ...]:
        return tuple((f.name, getattr(self, f.name)) for f in fields(self))


@dataclass(frozen=True)
class ProjectionResult:
    tax_year: int
    filing_status: str
    state: str
    gross_income: Decimal  # W-2 wages (before pretax) + all 1099/other income
    wage_income: Decimal  # W-2 wages before pretax deductions
    liabilities: Liabilities

    @property
    def total_liability(self) -> Decimal:
        return self.liabilities.total

    @property
    def effective_rate(self) -> Decimal:
        """Total liability / total gross income (0 when there is no income)."""
        if self.gross_income <= 0:
            return _ZERO
        return self.total_liability / self.gross_income
