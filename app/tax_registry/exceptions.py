from __future__ import annotations


class MissingTaxYear(LookupError):
    def __init__(self, jurisdiction: str, year: int, available: list[int]):
        self.jurisdiction = jurisdiction
        self.year = year
        self.available = available
        super().__init__(
            f"No tax data for {jurisdiction} {year} (available: {available})"
        )


class TaxTableSchemaError(ValueError):
    def __init__(self, jurisdiction: str, year: int, detail: str):
        self.jurisdiction = jurisdiction
        self.year = year
        self.detail = detail
        super().__init__(
            f"Invalid tax table for {jurisdiction} {year}: {detail}"
        )
