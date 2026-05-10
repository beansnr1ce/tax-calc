from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from .exceptions import MissingTaxYear, TaxTableSchemaError
from .models import Bracket, BracketTable, TaxYearProfile
from .schemas import TaxYearSchema
from .sources import TaxDataSource


def _coerce_decimals(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _coerce_decimals(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_coerce_decimals(v) for v in value]
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return value
    return value


class TaxTableRegistry:
    def __init__(
        self,
        source: TaxDataSource,
        *,
        fallback_year: int | None = None,
        eager: bool = True,
    ):
        self._source = source
        self._fallback_year = fallback_year
        self._available: frozenset[tuple[str, int]] = frozenset(source.list_available())
        self._cache: dict[tuple[str, int], TaxYearSchema] = {}
        if eager:
            for jurisdiction, year in self._available:
                self._validate(jurisdiction, year)

    def _validate(self, jurisdiction: str, year: int) -> TaxYearSchema:
        cached = self._cache.get((jurisdiction, year))
        if cached is not None:
            return cached
        raw = self._source.load(jurisdiction, year)
        try:
            parsed = TaxYearSchema.model_validate(raw)
        except ValidationError as e:
            raise TaxTableSchemaError(jurisdiction, year, str(e)) from e
        self._cache[(jurisdiction, year)] = parsed
        return parsed

    def with_fallback(self, fallback_year: int) -> "TaxTableRegistry":
        clone = TaxTableRegistry(
            self._source, fallback_year=fallback_year, eager=False
        )
        clone._cache = self._cache
        return clone

    def _resolve_year(self, jurisdiction: str, year: int) -> int:
        if (jurisdiction, year) in self._available:
            return year
        if (
            self._fallback_year is not None
            and (jurisdiction, self._fallback_year) in self._available
        ):
            return self._fallback_year
        raise MissingTaxYear(jurisdiction, year, self.years_for(jurisdiction))

    def jurisdictions(self) -> list[str]:
        return sorted({j for j, _ in self._available})

    def years_for(self, jurisdiction: str) -> list[int]:
        return sorted(y for j, y in self._available if j == jurisdiction)

    def has_year(self, jurisdiction: str, year: int) -> bool:
        return (jurisdiction, year) in self._available

    def profile(
        self, jurisdiction: str, year: int, filing_status: str
    ) -> TaxYearProfile:
        data_year = self._resolve_year(jurisdiction, year)
        parsed = self._validate(jurisdiction, data_year)
        status_data = parsed.filing_statuses[filing_status]
        brackets = tuple(
            Bracket(floor=b.floor, rate=b.rate) for b in status_data.brackets
        )
        return TaxYearProfile(
            jurisdiction=jurisdiction,
            year=year,
            filing_status=filing_status,
            brackets=BracketTable(brackets=brackets),
            standard_deduction=status_data.standard_deduction,
            dependent_credit=status_data.dependent_credit,
            extras=_coerce_decimals(dict(parsed.extras)),
            starting_point=parsed.starting_point,
            allows_itemized=parsed.allows_itemized,
            itemized_source=parsed.itemized_source,
        )

    def extra(self, jurisdiction: str, year: int, key: str) -> Any:
        data_year = self._resolve_year(jurisdiction, year)
        parsed = self._validate(jurisdiction, data_year)
        extras = _coerce_decimals(dict(parsed.extras))
        return extras[key]

    def federal_limit(self, year: int, key: str) -> Decimal:
        data_year = self._resolve_year("federal", year)
        parsed = self._validate("federal", data_year)
        return Decimal(parsed.limits[key])

    def quarterly_due_dates(self, year: int) -> tuple[date, ...]:
        data_year = self._resolve_year("federal", year)
        parsed = self._validate("federal", data_year)
        return tuple(date.fromisoformat(d) for d in parsed.quarterly_due_dates)
