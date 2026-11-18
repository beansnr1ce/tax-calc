"""Projection engine: composes tax facts, the federal engine and the state
engine registry into a typed `ProjectionResult`.

Deliberately does not go through the legacy `calculate_all` dict.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from app.federal_tax import FederalEngine
from app.state_tax import StateEngineRegistry
from app.tax_facts import FactsError, FieldError, SalaryFacts, TaxFacts, build_facts
from app.tax_registry import TaxTableRegistry

from .result import Liabilities, ProjectionResult

_ZERO = Decimal("0")


class ProjectionEngine:
    def __init__(
        self,
        tax_tables: TaxTableRegistry,
        state_engines: StateEngineRegistry,
        federal_engine: FederalEngine | None = None,
    ) -> None:
        self._tables = tax_tables
        self._engines = state_engines
        self._fed = federal_engine or FederalEngine(tax_tables)

    def project(self, raw_inputs: Mapping[str, Any]) -> ProjectionResult:
        facts = self._build_facts(raw_inputs)

        fed = self._fed.compute(facts)
        fed_itemized = fed.itemized.total if fed.use_itemized else _ZERO
        state_result = self._engines.get(facts.state).compute(
            facts.to_state_input(
                federal_agi=fed.agi,
                federal_taxable_income=fed.taxable_income,
                federal_itemized=fed_itemized,
            )
        )

        return ProjectionResult(
            tax_year=facts.tax_year,
            filing_status=facts.filing_status,
            state=facts.state,
            gross_income=fed.gross_income,
            wage_income=facts.total_w2_wages,
            liabilities=Liabilities(
                federal_income_tax=fed.final_tax,
                self_employment_tax=fed.se_tax.total,
                state_income_tax=state_result.final_tax,
                state_sdi=self._sdi(facts),
            ),
        )

    def _build_facts(self, raw: Mapping[str, Any]) -> TaxFacts:
        # The withholding builder defaults state to CA; a projection
        # requires the user to choose it.
        errors: list[FieldError] = []
        if raw.get("state") in (None, ""):
            errors.append(FieldError(field="state", code="missing", message="state is required"))
        try:
            facts = build_facts(
                raw,
                tax_tables=self._tables,
                state_engines=self._engines,
                require_frequency=False,
            )
        except FactsError as e:
            raise FactsError(errors + list(e.errors)) from None
        if errors:
            raise FactsError(errors)
        return facts

    def _sdi(self, facts: TaxFacts) -> Decimal:
        """State disability insurance, per employee: each salary's SDI wages
        are capped at the wage base separately (unlike the household-combined
        addon the withholding calculator's CaliforniaEngine reports)."""
        params = self._sdi_params(facts.state, facts.tax_year)
        if params is None:
            return _ZERO
        salaries = [s for s in (facts.salary1, facts.salary2) if s is not None]
        return sum(
            (min(_sdi_wages(s), params["wage_base"]) * params["rate"] for s in salaries),
            _ZERO,
        )

    def _sdi_params(self, state: str, year: int) -> Mapping[str, Decimal] | None:
        if state not in self._tables.jurisdictions():
            return None
        try:
            return self._tables.extra(state, year, "sdi")
        except KeyError:
            return None


def _sdi_wages(salary: SalaryFacts) -> Decimal:
    """SDI wages = gross less Section 125 (cafeteria plan) deductions.
    401(k), IRA and `other` pretax deductions do not reduce SDI wages."""
    return max(_ZERO, salary.annual - salary.pretax.section_125)
