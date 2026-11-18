"""YTD / paystub projection: mid-year inputs from paystubs, projected to
year end, compared with the projected liability per authority.

Self-contained so the projection engine only has to (1) parse the `ytd`
payload, (2) swap projected wages into the facts and (3) settle the
resulting liabilities against projected payments.

Payload shape (amounts optional, blank = 0, except `gross`)::

    "ytd": {
        "salary1": {"gross", "federal_withheld", "state_withheld",
                    "sdi_withheld", "federal_per_paycheck",
                    "state_per_paycheck", "paychecks_remaining"},
        "salary2": {...same...},
        "federal_estimated_payments", "state_estimated_payments"
    }

Once any YTD figure is entered, every salary in the household needs a pay
frequency and a `salaryN` block with `gross`; otherwise projected wages and
payments would silently fall back to the plain annual salary.

Assumptions:
- Salary is constant: each remaining paycheck = annual salary ÷ periods.
- YTD figures include any paycheck dated on the as-of date, so the default
  paychecks remaining counts paydays strictly after it.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Mapping

from app.state_tax.states.california import sdi_taxable_wages
from app.tax_facts import (
    FieldError,
    SalaryFacts,
    TaxFacts,
    is_missing,
    parse_decimal,
    parse_whole_number,
)

if TYPE_CHECKING:
    from .result import Liabilities

_ZERO = Decimal("0")
SALARY_AMOUNT_FIELDS = (
    "gross",
    "federal_withheld",
    "state_withheld",
    "sdi_withheld",
    "federal_per_paycheck",
    "state_per_paycheck",
)
HOUSEHOLD_AMOUNT_FIELDS = ("federal_estimated_payments", "state_estimated_payments")


# --- inputs -----------------------------------------------------------------


@dataclass(frozen=True)
class SalaryYtdInput:
    gross: Decimal = _ZERO
    federal_withheld: Decimal = _ZERO
    state_withheld: Decimal = _ZERO
    sdi_withheld: Decimal = _ZERO
    federal_per_paycheck: Decimal = _ZERO
    state_per_paycheck: Decimal = _ZERO
    paychecks_remaining: int | None = None  # None → default from as-of date


@dataclass(frozen=True)
class YtdInput:
    salary1: SalaryYtdInput | None = None
    salary2: SalaryYtdInput | None = None
    federal_estimated_payments: Decimal = _ZERO
    state_estimated_payments: Decimal = _ZERO


def parse_ytd(payload: Mapping[str, Any]) -> tuple[YtdInput | None, list[FieldError]]:
    """Reads `payload["ytd"]` for the household's salaries. Returns (None, [])
    when no YTD data was supplied (all blank)."""
    raw = payload.get("ytd")
    if not isinstance(raw, Mapping):
        return None, []
    keys = _salary_keys(payload)
    errors: list[FieldError] = []
    salaries = {key: _salary_input(raw.get(key), f"ytd.{key}", errors) for key in keys}
    household = {f: _amount(raw.get(f), f"ytd.{f}", errors) for f in HOUSEHOLD_AMOUNT_FIELDS}
    if all(s is None for s in salaries.values()) and all(
        is_missing(raw.get(f)) for f in HOUSEHOLD_AMOUNT_FIELDS
    ):
        return None, errors
    errors += _required_once_present(payload, raw, keys)
    return YtdInput(**salaries, **household), errors


def _salary_keys(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return ("salary1", "salary2") if payload.get("dual_income") else ("salary1",)


def _salary_input(block: Any, prefix: str, errors: list[FieldError]) -> SalaryYtdInput | None:
    if not isinstance(block, Mapping) or all(
        is_missing(block.get(f)) for f in (*SALARY_AMOUNT_FIELDS, "paychecks_remaining")
    ):
        return None
    remaining = block.get("paychecks_remaining")
    return SalaryYtdInput(
        **{f: _amount(block.get(f), f"{prefix}.{f}", errors) for f in SALARY_AMOUNT_FIELDS},
        paychecks_remaining=None
        if is_missing(remaining)
        else parse_whole_number(remaining, f"{prefix}.paychecks_remaining", errors),
    )


def _amount(value: Any, field: str, errors: list[FieldError]) -> Decimal:
    if is_missing(value):
        return _ZERO
    parsed = parse_decimal(value, field, errors, non_negative=True)
    return _ZERO if parsed is None else parsed


def _required_once_present(
    payload: Mapping[str, Any], raw: Mapping[str, Any], keys: tuple[str, ...]
) -> list[FieldError]:
    """Every salary needs a pay frequency and YTD gross once YTD data is present."""
    errors: list[FieldError] = []
    for key in keys:
        if is_missing(payload.get(f"{key}_frequency")):
            errors.append(
                FieldError(
                    field=f"{key}_frequency",
                    code="frequency_required",
                    message=f"{key}_frequency is required when YTD paystub data is entered",
                )
            )
        block = raw.get(key)
        if not isinstance(block, Mapping) or is_missing(block.get("gross")):
            errors.append(
                FieldError(
                    field=f"ytd.{key}.gross",
                    code="missing",
                    message=f"ytd.{key}.gross (YTD gross wages) is required when YTD paystub data is entered",
                )
            )
    return errors


# --- paychecks remaining ----------------------------------------------------


def default_paychecks_remaining(frequency: str, as_of: date, tax_year: int) -> int:
    """Paydays in `tax_year` strictly after `as_of`.

    Weekly/biweekly have no calendar anchor: whole 7/14-day steps left until
    Dec 31. Semimonthly pays the 15th and last day of each month; monthly the
    last day; quarterly the last day of each quarter; annually Dec 31.
    """
    if as_of.year > tax_year:
        return 0
    if as_of.year < tax_year:
        as_of = date(tax_year - 1, 12, 31)
    if frequency in ("weekly", "biweekly"):
        days = (date(tax_year, 12, 31) - as_of).days
        return days // (7 if frequency == "weekly" else 14)
    return sum(1 for d in _paydays(frequency, tax_year) if d > as_of)


def _paydays(frequency: str, year: int) -> list[date]:
    def month_end(m: int) -> date:
        return date(year, m, calendar.monthrange(year, m)[1])

    if frequency == "semimonthly":
        return [d for m in range(1, 13) for d in (date(year, m, 15), month_end(m))]
    if frequency == "monthly":
        return [month_end(m) for m in range(1, 13)]
    if frequency == "quarterly":
        return [month_end(m) for m in (3, 6, 9, 12)]
    if frequency == "annually":
        return [date(year, 12, 31)]
    raise KeyError(frequency)


# --- results ----------------------------------------------------------------


@dataclass(frozen=True)
class SalaryYtd:
    """One salary projected to year end."""

    paychecks_remaining: int
    projected_wages: Decimal
    remaining_wages: Decimal = _ZERO
    # Payroll-tax wages (gross less Section 125), the SDI wage basis
    projected_payroll_wages: Decimal = _ZERO
    remaining_payroll_wages: Decimal = _ZERO
    federal_payments: Decimal = _ZERO
    state_payments: Decimal = _ZERO
    sdi_payments: Decimal = _ZERO


@dataclass(frozen=True)
class AuthorityBalance:
    liability: Decimal
    payments: Decimal

    @property
    def refund_or_balance_due(self) -> Decimal:
        """Payments − liability: positive = refund, negative = balance due."""
        return self.payments - self.liability

    @property
    def refund(self) -> Decimal:
        return max(_ZERO, self.refund_or_balance_due)

    @property
    def balance_due(self) -> Decimal:
        return max(_ZERO, -self.refund_or_balance_due)


@dataclass(frozen=True)
class YtdProjection:
    as_of: date
    salary1: SalaryYtd
    salary2: SalaryYtd | None
    federal: AuthorityBalance  # income tax + SE tax; FICA excluded
    state: AuthorityBalance  # state income tax
    sdi: AuthorityBalance
    # Suggested extra withholding per paycheck on `suggestion_salary`, the
    # salary with the most paychecks remaining (W-4 Step 4(c) federal, DE 4
    # state). None when no balance is due or no paychecks remain.
    suggestion_salary: str | None = None
    suggestion_paychecks: int = 0
    federal_extra_per_paycheck: Decimal | None = None
    state_extra_per_paycheck: Decimal | None = None


# --- engine-facing steps ----------------------------------------------------


def project_salaries(
    facts: TaxFacts, ytd: YtdInput, as_of: date
) -> tuple[TaxFacts, dict[str, SalaryYtd]]:
    """Swap projected wages into the facts. Payments are filled in later by
    `settle`."""
    projected: dict[str, SalaryYtd] = {}
    updates: dict[str, SalaryFacts] = {}
    for key, salary in zip(("salary1", "salary2"), facts.salaries):
        block: SalaryYtdInput = getattr(ytd, key)
        paychecks = block.paychecks_remaining
        if paychecks is None:
            paychecks = default_paychecks_remaining(salary.frequency, as_of, facts.tax_year)
        remaining = paychecks * salary.per_paycheck(salary.annual)
        projected_salary = replace(salary, annual=block.gross + remaining)
        projected[key] = SalaryYtd(
            paychecks_remaining=paychecks,
            projected_wages=projected_salary.annual,
            remaining_wages=remaining,
            projected_payroll_wages=projected_salary.payroll_wages,
            remaining_payroll_wages=paychecks * salary.per_paycheck(salary.payroll_wages),
        )
        updates[key] = projected_salary
    return replace(facts, **updates), projected


def settle(
    ytd: YtdInput,
    projected: Mapping[str, SalaryYtd],
    liabilities: Liabilities,
    *,
    sdi_params: Mapping[str, Decimal] | None,
    as_of: date,
) -> YtdProjection:
    """Projected payments per authority vs. projected liability, plus the
    extra-withholding suggestion when a balance is due.

    The federal liability is income tax + self-employment tax. Employee FICA
    is left out: payroll withholds it exactly."""
    salaries: dict[str, SalaryYtd] = {}
    for key, s in projected.items():
        block: SalaryYtdInput = getattr(ytd, key)
        paychecks = s.paychecks_remaining
        salaries[key] = replace(
            s,
            federal_payments=block.federal_withheld + paychecks * block.federal_per_paycheck,
            state_payments=block.state_withheld + paychecks * block.state_per_paycheck,
            sdi_payments=block.sdi_withheld + _remaining_sdi(s, sdi_params),
        )

    def total(attr: str) -> Decimal:
        return sum((getattr(s, attr) for s in salaries.values()), _ZERO)

    federal = AuthorityBalance(
        liabilities.federal_income_tax + liabilities.self_employment_tax,
        total("federal_payments") + ytd.federal_estimated_payments,
    )
    state = AuthorityBalance(
        liabilities.state_income_tax, total("state_payments") + ytd.state_estimated_payments
    )
    sdi = AuthorityBalance(liabilities.state_sdi, total("sdi_payments"))

    # Suggest on the salary with the most paychecks left (ties → salary1).
    target = max(salaries, key=lambda k: salaries[k].paychecks_remaining)
    paychecks = salaries[target].paychecks_remaining

    def extra(b: AuthorityBalance) -> Decimal | None:
        return b.balance_due / paychecks if paychecks > 0 and b.balance_due > 0 else None

    federal_extra, state_extra = extra(federal), extra(state)
    return YtdProjection(
        as_of=as_of,
        salary1=salaries["salary1"],
        salary2=salaries.get("salary2"),
        federal=federal,
        state=state,
        sdi=sdi,
        suggestion_salary=target if (federal_extra or state_extra) else None,
        suggestion_paychecks=paychecks,
        federal_extra_per_paycheck=federal_extra,
        state_extra_per_paycheck=state_extra,
    )


def _remaining_sdi(s: SalaryYtd, params: Mapping[str, Decimal] | None) -> Decimal:
    """No per-paycheck SDI input: SDI rate × remaining payroll wages (the
    same gross − Section 125 basis as the SDI liability). With a wage base,
    only the part YTD wages have not used up counts."""
    if params is None:
        return _ZERO
    ytd_wages = max(_ZERO, s.projected_payroll_wages - s.remaining_payroll_wages)
    remaining = sdi_taxable_wages(s.projected_payroll_wages, params) - sdi_taxable_wages(
        ytd_wages, params
    )
    return remaining * params["rate"]
