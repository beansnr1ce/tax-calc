from __future__ import annotations

from app.tax_registry import TaxTableRegistry

from .engines import NullStateEngine, StandardStateEngine

NO_TAX_STATES = frozenset(
    {"TX", "FL", "NV", "WA", "SD", "WY", "AK", "NH", "TN"}
)


class UnsupportedJurisdiction(LookupError):
    def __init__(self, jurisdiction: str, supported: list[str]):
        self.jurisdiction = jurisdiction
        self.supported = supported
        super().__init__(
            f"No state engine for {jurisdiction!r} (supported: {supported})"
        )


class StateEngineRegistry:
    def __init__(self, registry: TaxTableRegistry):
        self._tables = registry
        self._overrides: dict[str, type] = {}

    def register(self, jurisdiction: str, engine_cls: type) -> None:
        self._overrides[jurisdiction] = engine_cls

    def get(self, jurisdiction: str):
        if jurisdiction in NO_TAX_STATES:
            return NullStateEngine(jurisdiction)
        if jurisdiction in self._overrides:
            return self._overrides[jurisdiction](jurisdiction, self._tables)
        if jurisdiction in self._tables.jurisdictions():
            return StandardStateEngine(jurisdiction, self._tables)
        supported = sorted(
            set(NO_TAX_STATES)
            | set(self._overrides)
            | set(self._tables.jurisdictions())
        )
        raise UnsupportedJurisdiction(jurisdiction, supported)
