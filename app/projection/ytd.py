"""YTD / paystub projection: mid-year inputs from paystubs, projected to
year end, compared with the projected liability per authority.

Self-contained so the projection engine only has to (1) parse the `ytd`
payload, (2) swap projected wages into the facts and (3) settle the
resulting liabilities against projected payments.

Payload shape (all amounts optional, blank = 0)::

    "ytd": {
        "salary1": {"gross", "federal_withheld", "state_withheld",
                    "sdi_withheld", "federal_per_paycheck",
                    "state_per_paycheck", "paychecks_remaining"},
        "salary2": {...same...},
        "federal_estimated_payments", "state_estimated_payments"
    }

Assumptions:
- Salary is constant: each remaining paycheck = annual salary ÷ periods.
- YTD figures include any paycheck dated on the as-of date, so the default
  paychecks remaining counts paydays strictly after it.
- A salary without a `salaryN` block keeps its plain annual salary and
  contributes no withholding.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from app.pay_periods import PAY_FREQUENCIES
from app.tax_facts import FieldError, SalaryFacts, TaxFacts

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


def parse_ytd(raw: Any) -> tuple[YtdInput | None, list[FieldError]]:
    """Returns (None, []) when no YTD data was supplied (all blank)."""
    if not isinstance(raw, Mapping):
        return None, []
    errors: list[FieldError] = []
    salaries: dict[str, SalaryYtdInput | None] = {}
    for key in ("salary1", "salary2"):
        block = raw.get(key)
        if not isinstance(block, Mapping) or all(_blank(block.get(f)) for f in (*SALARY_AMOUNT_FIELDS, "paychecks_remaining")):
            salaries[key] = None
            continue
        amounts = {
            f: _amount(block.get(f), f"ytd.{key}.{f}", errors) for f in SALARY_AMOUNT_FIELDS
        }
        salaries[key] = SalaryYtdInput(
            **amounts,
            paychecks_remaining=_count(
                block.get("paychecks_remaining"), f"ytd.{key}.paychecks_remaining", errors
            ),
        )
    household = {f: _amount(raw.get(f), f"ytd.{f}", errors) for f in HOUSEHOLD_AMOUNT_FIELDS}
    if all(s is None for s in salaries.values()) and all(
        _blank(raw.get(f)) for f in HOUSEHOLD_AMOUNT_FIELDS
    ):
        return None, errors
    return YtdInput(**salaries, **household), errors


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _amount(v: Any, field: str, errors: list[FieldError]) -> Decimal:
    if _blank(v):
        return _ZERO
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        errors.append(FieldError(field=field, code="type", message=f"{field} must be a number"))
        return _ZERO
    if not d.is_finite() or d < 0:
        errors.append(FieldError(field=field, code="range", message=f"{field} must be ≥ 0"))
        return _ZERO
    return d


def _count(v: Any, field: str, errors: list[FieldError]) -> int | None:
    if _blank(v):
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        d = None
    if d is None or not d.is_finite() or d != d.to_integral_value():
        errors.append(FieldError(field=field, code="type", message=f"{field} must be a whole number"))
        return None
    if d < 0:
        errors.append(FieldError(field=field, code="range", message=f"{field} must be ≥ 0"))
        return None
    return int(d)


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
    federal_payments: Decimal = _ZERO
    state_payments: Decimal = _ZERO
    sdi_payments: Decimal = _ZERO


@dataclass(frozen=True)
class AuthorityBalance:
    liability: Decimal
    payments: Decimal

    @property
    def balance(self) -> Decimal:
        """Positive = refund, negative = balance due."""
        return self.payments - self.liability

    @property
    def refund(self) -> Decimal:
        return max(_ZERO, self.balance)

    @property
    def balance_due(self) -> Decimal:
        return max(_ZERO, -self.balance)


@dataclass(frozen=True)
class YtdProjection:
    as_of: date
    salary1: SalaryYtd
    salary2: SalaryYtd | None
    federal: AuthorityBalance  # income tax + SE tax; FICA excluded
    state: AuthorityBalance  # state income tax
    sdi: AuthorityBalance
    # Suggested extra withholding per paycheck on `suggestion_salary`
    # (W-4 Step 4(c) federal, DE 4 state). None when no balance is due or
    # no paychecks remain.
    suggestion_salary: str | None = None
    suggestion_paychecks: int = 0
    federal_extra_per_paycheck: Decimal | None = None
    state_extra_per_paycheck: Decimal | None = None


# --- engine-facing steps ----------------------------------------------------


def frequency_errors(raw: Mapping[str, Any]) -> list[FieldError]:
    """Pay frequency is required for every salary when YTD data is present."""
    keys = ["salary1"] + (["salary2"] if raw.get("dual_income") else [])
    return [
        FieldError(
            field=f"{k}_frequency",
            code="frequency_required",
            message=f"{k}_frequency is required when YTD paystub data is entered",
        )
        for k in keys
        if _blank(raw.get(f"{k}_frequency"))
    ]


def project_salaries(
    facts: TaxFacts, ytd: YtdInput, as_of: date
) -> tuple[TaxFacts, dict[str, SalaryYtd]]:
    """Swap projected wages into the facts. Payments are filled in later by
    `settle` (SDI needs the wage base)."""
    projected: dict[str, SalaryYtd] = {}
    updates: dict[str, SalaryFacts] = {}
    for key in ("salary1", "salary2"):
        salary: SalaryFacts | None = getattr(facts, key)
        if salary is None:
            continue
        block: SalaryYtdInput | None = getattr(ytd, key)
        n = default_paychecks_remaining(salary.frequency, as_of, facts.tax_year)
        if block is None:
            projected[key] = SalaryYtd(paychecks_remaining=n, projected_wages=salary.annual)
            continue
        if block.paychecks_remaining is not None:
            n = block.paychecks_remaining
        remaining = n * _per_paycheck(salary)
        wages = block.gross + remaining
        projected[key] = SalaryYtd(
            paychecks_remaining=n, projected_wages=wages, remaining_wages=remaining
        )
        updates[key] = replace(salary, annual=wages)
    return replace(facts, **updates), projected


def _per_paycheck(salary: SalaryFacts) -> Decimal:
    return salary.annual / PAY_FREQUENCIES[salary.frequency]


def settle(
    ytd: YtdInput,
    projected: Mapping[str, SalaryYtd],
    *,
    federal_liability: Decimal,
    state_liability: Decimal,
    sdi_liability: Decimal,
    sdi_params: Mapping[str, Decimal] | None,
    as_of: date,
) -> YtdProjection:
    """Projected payments per authority vs. projected liability, plus the
    extra-withholding suggestion when a balance is due."""
    salaries: dict[str, SalaryYtd] = {}
    for key, s in projected.items():
        block: SalaryYtdInput | None = getattr(ytd, key)
        if block is None:
            salaries[key] = s
            continue
        n = s.paychecks_remaining
        salaries[key] = replace(
            s,
            federal_payments=block.federal_withheld + n * block.federal_per_paycheck,
            state_payments=block.state_withheld + n * block.state_per_paycheck,
            sdi_payments=block.sdi_withheld + _remaining_sdi(block, s, sdi_params),
        )

    def total(attr: str) -> Decimal:
        return sum((getattr(s, attr) for s in salaries.values()), _ZERO)

    federal = AuthorityBalance(
        federal_liability, total("federal_payments") + ytd.federal_estimated_payments
    )
    state = AuthorityBalance(
        state_liability, total("state_payments") + ytd.state_estimated_payments
    )
    sdi = AuthorityBalance(sdi_liability, total("sdi_payments"))

    # Suggest on the salary with the most paychecks left (ties → salary1).
    target = max(salaries, key=lambda k: salaries[k].paychecks_remaining)
    n = salaries[target].paychecks_remaining

    def extra(b: AuthorityBalance) -> Decimal | None:
        return b.balance_due / n if n > 0 and b.balance_due > 0 else None

    fed_extra, state_extra = extra(federal), extra(state)
    return YtdProjection(
        as_of=as_of,
        salary1=salaries["salary1"],
        salary2=salaries.get("salary2"),
        federal=federal,
        state=state,
        sdi=sdi,
        suggestion_salary=target if (fed_extra or state_extra) else None,
        suggestion_paychecks=n,
        federal_extra_per_paycheck=fed_extra,
        state_extra_per_paycheck=state_extra,
    )


def _remaining_sdi(
    block: SalaryYtdInput, s: SalaryYtd, params: Mapping[str, Decimal] | None
) -> Decimal:
    """No per-paycheck SDI input: SDI rate × remaining wages, limited to the
    part of the wage base YTD gross has not used up."""
    if params is None:
        return _ZERO
    room = max(_ZERO, params["wage_base"] - block.gross)
    return min(s.remaining_wages, room) * params["rate"]
