from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class Bracket:
    floor: Decimal
    rate: Decimal


@dataclass(frozen=True)
class BracketTable:
    brackets: tuple[Bracket, ...]

    def tax_on(self, taxable: Decimal) -> Decimal:
        if taxable <= 0:
            return Decimal("0")
        total = Decimal("0")
        for i, bracket in enumerate(self.brackets):
            if taxable <= bracket.floor:
                break
            next_floor = (
                self.brackets[i + 1].floor
                if i + 1 < len(self.brackets)
                else taxable
            )
            top = min(taxable, next_floor)
            total += (top - bracket.floor) * bracket.rate
        return total


@dataclass(frozen=True)
class TaxYearProfile:
    jurisdiction: str
    year: int
    filing_status: str
    brackets: BracketTable
    standard_deduction: Decimal
    dependent_credit: Decimal
    extras: Mapping[str, Any]
    starting_point: str = "federal_agi"
    allows_itemized: bool = True
    itemized_source: str = "federal"
