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

from .result import EmployeeFica, Liabilities, ProjectionResult

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

        fica = self._fica(facts)

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
                social_security=fica.social_security,
                medicare=fica.total_medicare,
            ),
            fica=fica,
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

    def _fica(self, facts: TaxFacts) -> EmployeeFica:
        """Employee FICA from the federal `extras.fica` table. Social Security
        per salary, capped at the wage base; Medicare on all FICA wages;
        Additional Medicare on combined household FICA wages above the
        filing-status threshold."""
        p = self._tables.extra("federal", facts.tax_year, "fica")
        w1 = _payroll_wages(facts.salary1)
        w2 = _payroll_wages(facts.salary2) if facts.salary2 is not None else _ZERO
        ss_base = p["ss_wage_base"]
        threshold = p["additional_medicare_threshold"][facts.filing_status]
        household = w1 + w2
        return EmployeeFica(
            salary1_fica_wages=w1,
            salary2_fica_wages=w2,
            salary1_social_security=min(w1, ss_base) * p["ss_rate"],
            salary2_social_security=min(w2, ss_base) * p["ss_rate"],
            medicare=household * p["medicare_rate"],
            additional_medicare=max(_ZERO, household - threshold)
            * p["additional_medicare_rate"],
        )

    def _sdi(self, facts: TaxFacts) -> Decimal:
        """State disability insurance, per employee: each salary's SDI wages
        are capped at the wage base separately (unlike the household-combined
        addon the withholding calculator's CaliforniaEngine reports)."""
        params = self._sdi_params(facts.state, facts.tax_year)
        if params is None:
            return _ZERO
        salaries = [s for s in (facts.salary1, facts.salary2) if s is not None]
        return sum(
            (min(_payroll_wages(s), params["wage_base"]) * params["rate"] for s in salaries),
            _ZERO,
        )

    def _sdi_params(self, state: str, year: int) -> Mapping[str, Decimal] | None:
        if state not in self._tables.jurisdictions():
            return None
        try:
            return self._tables.extra(state, year, "sdi")
        except KeyError:
            return None


def _payroll_wages(salary: SalaryFacts) -> Decimal:
    """Payroll-tax wages (FICA, SDI) = gross less Section 125 (cafeteria plan)
    deductions. 401(k), IRA and `other` pretax deductions do not reduce them."""
    return max(_ZERO, salary.annual - salary.pretax.section_125)
