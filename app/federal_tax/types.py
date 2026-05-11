from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.tax_registry import BracketLine


@dataclass(frozen=True)
class ItemizedBreakdown:
    charitable: Decimal = Decimal("0")
    mortgage_interest: Decimal = Decimal("0")
    salt: Decimal = Decimal("0")
    salt_original: Decimal = Decimal("0")
    salt_capped: bool = False
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
class SETaxResult:
    se_income: Decimal = Decimal("0")
    ss_tax: Decimal = Decimal("0")
    medicare_tax: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    deduction: Decimal = Decimal("0")


@dataclass(frozen=True)
class CreditResult:
    amount: Decimal
    explanation: str
    phased_out: Decimal = Decimal("0")


def _f(d: Decimal) -> float:
    """Round Decimal to 2 places and widen to float — the JSON seam."""
    return float(round(d, 2))


@dataclass(frozen=True)
class FederalResult:
    # income
    w2_income: Decimal
    salary1_annual: Decimal
    salary2_annual: Decimal
    additional_income: Decimal
    gross_income: Decimal
    pretax_deductions: Decimal
    # AGI inputs
    se_tax: SETaxResult
    student_loan: CreditResult
    agi: Decimal
    # deduction choice
    standard_deduction: Decimal
    itemized: ItemizedBreakdown
    use_itemized: bool
    deduction_used: Decimal
    # tax
    taxable_income: Decimal
    tax_before_credits: Decimal
    bracket_breakdown: tuple[BracketLine, ...]
    child_tax_credit: CreditResult
    final_tax: Decimal

    def to_legacy_dict(self) -> dict[str, Any]:
        itm = self.itemized
        breakdown: dict[str, Any] = {
            "charitable": _f(itm.charitable),
            "mortgage_interest": _f(itm.mortgage_interest),
            "medical": _f(itm.medical),
            "other": _f(itm.other),
            "salt": _f(itm.salt),
            "salt_capped": itm.salt_capped,
            "salt_original": _f(itm.salt_original),
        }
        return {
            "gross_income": _f(self.gross_income),
            "w2_income": _f(self.w2_income),
            "salary1_annual": _f(self.salary1_annual),
            "salary2_annual": _f(self.salary2_annual),
            "additional_income": _f(self.additional_income),
            "pretax_deductions": _f(self.pretax_deductions),
            "se_tax_deduction": _f(self.se_tax.deduction),
            "student_loan_deduction": {
                "deduction": _f(self.student_loan.amount),
                "explanation": self.student_loan.explanation,
            },
            "agi": _f(self.agi),
            "standard_deduction": float(self.standard_deduction),
            "itemized_deduction": {
                "total": _f(itm.total),
                "breakdown": breakdown,
            },
            "use_itemized": self.use_itemized,
            "deduction_used": _f(self.deduction_used),
            "taxable_income": _f(self.taxable_income),
            "tax_before_credits": _f(self.tax_before_credits),
            "bracket_breakdown": [
                {
                    "bracket_start": float(line.floor),
                    "bracket_end": float(line.ceiling)
                    if line.ceiling is not None
                    else "unlimited",
                    "rate": float(line.rate * 100),
                    "taxable_amount": _f(line.taxable_amount),
                    "tax": _f(line.tax),
                }
                for line in self.bracket_breakdown
            ],
            "child_tax_credit": {
                "total": _f(self.child_tax_credit.amount),
                "phased_out": _f(self.child_tax_credit.phased_out),
                "explanation": self.child_tax_credit.explanation,
            },
            "final_tax": _f(self.final_tax),
            "se_tax": {
                "total": _f(self.se_tax.total),
                "ss_tax": _f(self.se_tax.ss_tax),
                "medicare_tax": _f(self.se_tax.medicare_tax),
                "se_income": _f(self.se_tax.se_income),
                "deduction": _f(self.se_tax.deduction),
            },
        }
