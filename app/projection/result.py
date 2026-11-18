"""Typed result of an Annual Tax Projection.

Frozen dataclasses, Decimal amounts, unrounded. Serialization (rounding,
JSON shape) happens at the HTTP route, not here.

Extension points for later work:
- New liability lines are added as fields on
  `Liabilities`; `Liabilities.total` sums every field, so they count toward
  `total_liability` and the effective rate automatically.
- New result sections (marginal rates, take-home, YTD) are added as
  defaulted fields on `ProjectionResult`.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal

from .ytd import YtdProjection

_ZERO = Decimal("0")


@dataclass(frozen=True)
class Liabilities:
    """Projected annual liability per authority. Every field is a Decimal
    amount and part of the total."""

    federal_income_tax: Decimal = _ZERO
    self_employment_tax: Decimal = _ZERO
    state_income_tax: Decimal = _ZERO
    state_sdi: Decimal = _ZERO
    social_security: Decimal = _ZERO  # Employee FICA
    medicare: Decimal = _ZERO  # Employee FICA, incl. Additional Medicare

    @property
    def total(self) -> Decimal:
        return sum((getattr(self, f.name) for f in fields(self)), _ZERO)

    def items(self) -> tuple[tuple[str, Decimal], ...]:
        return tuple((f.name, getattr(self, f.name)) for f in fields(self))


@dataclass(frozen=True)
class EmployeeFica:
    """Employee FICA breakdown. Social Security is per salary (each capped at
    the wage base); Additional Medicare is household-level (Form 8959)."""

    salary1_fica_wages: Decimal = _ZERO
    salary2_fica_wages: Decimal = _ZERO
    salary1_social_security: Decimal = _ZERO
    salary2_social_security: Decimal = _ZERO
    medicare: Decimal = _ZERO  # regular Medicare on all FICA wages
    additional_medicare: Decimal = _ZERO

    @property
    def social_security(self) -> Decimal:
        return self.salary1_social_security + self.salary2_social_security

    @property
    def total_medicare(self) -> Decimal:
        return self.medicare + self.additional_medicare

    @property
    def total(self) -> Decimal:
        return self.social_security + self.total_medicare


@dataclass(frozen=True)
class ProjectionResult:
    tax_year: int
    filing_status: str
    state: str
    gross_income: Decimal  # W-2 wages (before pretax) + all 1099/other income
    wage_income: Decimal  # W-2 wages before pretax deductions
    liabilities: Liabilities
    fica: EmployeeFica = EmployeeFica()
    # YTD / paystub projection (#22); None unless YTD data was supplied.
    ytd: YtdProjection | None = None

    @property
    def total_liability(self) -> Decimal:
        return self.liabilities.total

    @property
    def effective_rate(self) -> Decimal:
        """Total liability / total gross income (0 when there is no income)."""
        if self.gross_income <= 0:
            return _ZERO
        return self.total_liability / self.gross_income
