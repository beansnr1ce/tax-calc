from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

FilingStatus = Literal["single", "married_jointly", "head_of_household"]


def _reject_float(value: Any) -> Any:
    if isinstance(value, float) or isinstance(value, bool):
        raise ValueError("Money/rate values must be strings, not floats")
    return value


MoneyOrRate = Annotated[Decimal, BeforeValidator(_reject_float)]


class BracketSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    floor: MoneyOrRate
    rate: MoneyOrRate


class FilingStatusSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brackets: list[BracketSchema] = Field(min_length=1)
    standard_deduction: MoneyOrRate
    dependent_credit: MoneyOrRate


StartingPoint = Literal["federal_agi", "federal_taxable", "gross"]
ItemizedSource = Literal["federal", "state", "none"]


class TaxYearSchema(BaseModel):
    model_config = ConfigDict(extra="allow")
    kind: Literal["progressive", "flat", "none"]
    filing_statuses: dict[FilingStatus, FilingStatusSchema]
    starting_point: StartingPoint = "federal_agi"
    allows_itemized: bool = True
    itemized_source: ItemizedSource = "federal"
    extras: Mapping[str, Any] = Field(default_factory=dict)
    limits: Mapping[str, str] = Field(default_factory=dict)
    quarterly_due_dates: list[str] = Field(default_factory=list)
