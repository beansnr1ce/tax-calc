"""Projection engine: composes tax facts, the federal engine and the state
engine registry into a typed `ProjectionResult`.

Deliberately does not go through the legacy `calculate_all` dict.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence

from app.federal_tax import FederalEngine
from app.state_tax import StateEngineRegistry
from app.state_tax.states.california import sdi_taxable_wages
from app.tax_facts import FactsError, FieldError, TaxFacts, build_facts
from app.tax_registry import TaxTableRegistry

from . import ytd as paystub
from .result import (
    EmployeeFica,
    Liabilities,
    MarginalRates,
    ProjectionResult,
    SalaryFica,
    TakeHome,
)

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

    def project(
        self, raw_inputs: Mapping[str, Any], *, as_of: date | None = None
    ) -> ProjectionResult:
        """`as_of` (default: today) dates YTD paystub data; it only drives the
        default paychecks remaining."""
        ytd_input, ytd_errors = paystub.parse_ytd(raw_inputs)
        facts = self._build_facts(raw_inputs, ytd_errors)
        if ytd_input is not None:
            as_of = as_of or date.today()
            facts, ytd_salaries = paystub.project_salaries(facts, ytd_input, as_of)

        fed = self._fed.compute(facts)
        fed_itemized = fed.itemized.total if fed.use_itemized else _ZERO
        state_result = self._engines.get(facts.state).compute(
            facts.to_state_input(
                federal_agi=fed.agi,
                federal_taxable_income=fed.taxable_income,
                federal_itemized=fed_itemized,
            )
        )

        sdi_params = self._sdi_params(facts.state, facts.tax_year)
        fica = self._fica(facts)
        liabilities = Liabilities(
            federal_income_tax=fed.final_tax,
            self_employment_tax=fed.se_tax.total,
            state_income_tax=state_result.final_tax,
            state_sdi=_sdi(facts, sdi_params),
            social_security=fica.social_security,
            medicare=fica.total_medicare,
        )

        ytd = None
        if ytd_input is not None:
            ytd = paystub.settle(
                ytd_input, ytd_salaries, liabilities, sdi_params=sdi_params, as_of=as_of
            )

        return ProjectionResult(
            tax_year=facts.tax_year,
            filing_status=facts.filing_status,
            state=facts.state,
            gross_income=fed.gross_income,
            wage_income=facts.total_w2_wages,
            liabilities=liabilities,
            fica=fica,
            marginal_rates=MarginalRates(
                federal=self._marginal_rate("federal", facts, fed.taxable_income),
                state=self._marginal_rate(facts.state, facts, state_result.taxable_income),
            ),
            take_home=_take_home(facts, liabilities),
            ytd=ytd,
        )

    def _build_facts(
        self, raw: Mapping[str, Any], extra_errors: Sequence[FieldError] = ()
    ) -> TaxFacts:
        # The withholding builder defaults state to CA; a projection
        # requires the user to choose it.
        errors: list[FieldError] = list(extra_errors)
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
        table = self._tables.extra("federal", facts.tax_year, "fica")

        def salary_fica(wages: Decimal) -> SalaryFica:
            return SalaryFica(
                fica_wages=wages,
                social_security=min(wages, table["ss_wage_base"]) * table["ss_rate"],
            )

        household_wages = sum((s.payroll_wages for s in facts.salaries), _ZERO)
        threshold = table["additional_medicare_threshold"][facts.filing_status]
        return EmployeeFica(
            salary1=salary_fica(facts.salary1.payroll_wages),
            salary2=salary_fica(facts.salary2.payroll_wages) if facts.salary2 else None,
            medicare=household_wages * table["medicare_rate"],
            additional_medicare=max(_ZERO, household_wages - threshold)
            * table["additional_medicare_rate"],
        )

    def _marginal_rate(self, jurisdiction: str, facts: TaxFacts, taxable: Decimal) -> Decimal:
        """Bracket rate on the next dollar; 0 where there is no bracket table
        (no-income-tax states)."""
        if jurisdiction not in self._tables.jurisdictions():
            return _ZERO
        profile = self._tables.profile(jurisdiction, facts.tax_year, facts.filing_status)
        return profile.brackets.marginal_rate(taxable)

    def _sdi_params(self, state: str, year: int) -> Mapping[str, Decimal] | None:
        if state not in self._tables.jurisdictions():
            return None
        try:
            return self._tables.extra(state, year, "sdi")
        except KeyError:
            return None


def _sdi(facts: TaxFacts, params: Mapping[str, Decimal] | None) -> Decimal:
    """State disability insurance, per employee on payroll wages. With a
    `wage_base` in the table each salary is capped separately (unlike the
    household-combined addon the withholding calculator's CaliforniaEngine
    reports); without one (CA since 2024) wages are uncapped."""
    if params is None:
        return _ZERO
    return sum(
        (sdi_taxable_wages(s.payroll_wages, params) * params["rate"] for s in facts.salaries),
        _ZERO,
    )


def _take_home(facts: TaxFacts, liabilities: Liabilities) -> TakeHome:
    annual = (
        facts.total_w2_wages
        - facts.total_pretax
        - liabilities.federal_income_tax
        - liabilities.state_income_tax
        - liabilities.state_sdi
        - liabilities.social_security
        - liabilities.medicare
    )
    periods = _household_pay_periods(facts)
    return TakeHome(
        annual=annual,
        periods_per_year=periods,
        per_paycheck=annual / periods if periods else None,
    )


def _household_pay_periods(facts: TaxFacts) -> int | None:
    """Periods per year shared by every salary with a pay frequency; None if
    no salary has one or they differ."""
    known = {s.periods_per_year for s in facts.salaries if s.periods_per_year}
    return known.pop() if len(known) == 1 else None
