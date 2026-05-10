from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from app.pay_periods import PAY_FREQUENCIES
from app.state_tax import NO_TAX_STATES
from app.tax_registry import TaxTableRegistry

from .errors import FactsError, FieldError
from .facts import (
    ItemizedDeductions,
    PretaxDeductions,
    SalaryFacts,
    TaxFacts,
)

_VALID_FILING_STATUSES = {"single", "married_jointly", "head_of_household"}
_PRETAX_FIELDS = (
    "_401k",
    "ira",
    "health_insurance",
    "hsa",
    "fsa",
    "dental",
    "vision",
    "other",
)
_ITEMIZED_FIELDS = ("charitable", "mortgage_interest", "salt", "medical", "other")


def build_facts(
    payload: Mapping[str, Any],
    *,
    tax_tables: TaxTableRegistry,
    state_engines=None,
) -> TaxFacts:
    errors: list[FieldError] = []

    tax_year = _required_int(payload, "tax_year", errors)
    filing_status = _required_str(payload, "filing_status", errors)
    state = payload.get("state") or "CA"
    salary1_gross = _required_decimal(payload, "salary1_gross", errors, non_negative=True)
    salary1_frequency = _required_str(payload, "salary1_frequency", errors)

    if filing_status is not None and filing_status not in _VALID_FILING_STATUSES:
        errors.append(
            FieldError(
                field="filing_status",
                code="unknown_filing_status",
                message=f"unknown filing status {filing_status!r}",
                detail={"valid": sorted(_VALID_FILING_STATUSES)},
            )
        )

    if salary1_frequency is not None and salary1_frequency not in PAY_FREQUENCIES:
        errors.append(
            FieldError(
                field="salary1_frequency",
                code="unknown_frequency",
                message=f"unknown frequency {salary1_frequency!r}",
                detail={"valid": sorted(PAY_FREQUENCIES.keys())},
            )
        )

    valid_states = set(NO_TAX_STATES) | (set(tax_tables.jurisdictions()) - {"federal"})
    if state_engines is not None and hasattr(state_engines, "jurisdictions"):
        valid_states |= set(state_engines.jurisdictions())
    if state not in valid_states:
        errors.append(
            FieldError(
                field="state",
                code="unknown_state",
                message=f"unknown state {state!r}",
                detail={"valid": sorted(valid_states)},
            )
        )

    if tax_year is not None and tax_year not in tax_tables.years_for("federal"):
        errors.append(
            FieldError(
                field="tax_year",
                code="unknown_year",
                message=f"tax year {tax_year} not available",
                detail={"available": tax_tables.years_for("federal")},
            )
        )

    dual_income = bool(payload.get("dual_income", False))
    salary2 = None
    if dual_income:
        salary2 = _build_salary(payload, "salary2", errors, default_freq="biweekly")

    if errors:
        raise FactsError(errors)

    salary1_periods = PAY_FREQUENCIES[salary1_frequency]
    salary1_pretax = _build_pretax(payload, "pretax_deductions_1", salary1_periods, errors)

    if salary2 is not None:
        salary2_periods = PAY_FREQUENCIES[salary2.frequency]
        salary2_pretax = _build_pretax(payload, "pretax_deductions_2", salary2_periods, errors)
        salary2 = SalaryFacts(
            gross_per_period=salary2.gross_per_period,
            frequency=salary2.frequency,
            periods_per_year=salary2.periods_per_year,
            annual=salary2.annual,
            pretax=salary2_pretax,
        )

    salary1 = SalaryFacts(
        gross_per_period=salary1_gross,
        frequency=salary1_frequency,
        periods_per_year=salary1_periods,
        annual=salary1_gross * salary1_periods,
        pretax=salary1_pretax,
    )

    itemized = _build_itemized(payload, errors)

    _enforce_caps(salary1.pretax, salary2.pretax if salary2 else None, tax_tables, tax_year, errors)

    if errors:
        raise FactsError(errors)

    return TaxFacts(
        tax_year=tax_year,
        filing_status=filing_status,
        state=state,
        salary1=salary1,
        salary2=salary2,
        income_1099g=_optional_decimal(payload, "income_1099g"),
        income_1099nec=_optional_decimal(payload, "income_1099nec"),
        income_1099int_div=_optional_decimal(payload, "income_1099int_div"),
        other_income=_optional_decimal(payload, "other_income"),
        children_under_17=_optional_int(payload, "children_under_17"),
        other_dependents=_optional_int(payload, "other_dependents"),
        student_loan_interest=_optional_decimal(payload, "student_loan_interest"),
        itemized=itemized,
    )


def _build_salary(
    payload: Mapping[str, Any],
    prefix: str,
    errors: list[FieldError],
    *,
    default_freq: str,
) -> SalaryFacts | None:
    gross = _required_decimal(payload, f"{prefix}_gross", errors, non_negative=True)
    if gross is not None and gross == 0:
        errors.append(
            FieldError(
                field=f"{prefix}_gross",
                code="range",
                message=f"{prefix}_gross must be > 0 when dual_income is true",
            )
        )
        return None
    freq = payload.get(f"{prefix}_frequency", default_freq)
    if freq not in PAY_FREQUENCIES:
        errors.append(
            FieldError(
                field=f"{prefix}_frequency",
                code="unknown_frequency",
                message=f"unknown frequency {freq!r}",
                detail={"valid": sorted(PAY_FREQUENCIES.keys())},
            )
        )
        return None
    if gross is None:
        return None
    periods = PAY_FREQUENCIES[freq]
    return SalaryFacts(
        gross_per_period=gross,
        frequency=freq,
        periods_per_year=periods,
        annual=gross * periods,
        pretax=PretaxDeductions(),
    )


def _build_pretax(
    payload: Mapping[str, Any],
    key: str,
    periods: int,
    errors: list[FieldError],
) -> PretaxDeductions:
    raw = payload.get(key) or {}
    input_type = raw.get("input_type", "per_period")
    multiplier = periods if input_type == "per_period" else 1
    values = {}
    for fname in _PRETAX_FIELDS:
        v = raw.get(fname, 0) or 0
        try:
            d = Decimal(str(v))
        except Exception:
            errors.append(
                FieldError(
                    field=f"{key}.{fname}",
                    code="type",
                    message=f"{key}.{fname} must be numeric",
                )
            )
            d = Decimal("0")
        if d < 0:
            errors.append(
                FieldError(
                    field=f"{key}.{fname}",
                    code="range",
                    message=f"{key}.{fname} must be non-negative",
                )
            )
            d = Decimal("0")
        values[fname] = d * multiplier
    return PretaxDeductions(**values)


def _build_itemized(payload: Mapping[str, Any], errors: list[FieldError]) -> ItemizedDeductions:
    raw = payload.get("itemized_deductions") or {}
    values = {}
    for fname in _ITEMIZED_FIELDS:
        v = raw.get(fname, 0) or 0
        try:
            d = Decimal(str(v))
        except Exception:
            errors.append(
                FieldError(
                    field=f"itemized_deductions.{fname}",
                    code="type",
                    message=f"itemized_deductions.{fname} must be numeric",
                )
            )
            d = Decimal("0")
        if d < 0:
            errors.append(
                FieldError(
                    field=f"itemized_deductions.{fname}",
                    code="range",
                    message=f"itemized_deductions.{fname} must be non-negative",
                )
            )
            d = Decimal("0")
        values[fname] = d
    return ItemizedDeductions(**values)


def _enforce_caps(
    pretax1: PretaxDeductions,
    pretax2: PretaxDeductions | None,
    tax_tables: TaxTableRegistry,
    year: int,
    errors: list[FieldError],
) -> None:
    """Enforce contribution caps. 401k and IRA are per-person (per W-2);
    HSA is per-household (family cap)."""

    def _check(field: str, value: Decimal, cap_key: str) -> None:
        cap = tax_tables.federal_limit(year, cap_key)
        if value > cap:
            errors.append(
                FieldError(
                    field=field,
                    code="cap_exceeded",
                    message=f"{field} {value} exceeds {year} cap {cap}",
                    detail={"cap": cap, "year": year, "value": value},
                )
            )

    # Per-person caps
    _check("pretax_deductions_1._401k", pretax1._401k, "401k_employee_deferral")
    _check("pretax_deductions_1.ira", pretax1.ira, "ira_regular")
    if pretax2 is not None:
        _check("pretax_deductions_2._401k", pretax2._401k, "401k_employee_deferral")
        _check("pretax_deductions_2.ira", pretax2.ira, "ira_regular")

    # Household cap
    p2 = pretax2 if pretax2 is not None else PretaxDeductions()
    _check("pretax_deductions.hsa", pretax1.hsa + p2.hsa, "hsa_family")


def _is_missing(value: Any) -> bool:
    return value is None or value == ""


def _required_str(payload: Mapping[str, Any], field: str, errors: list[FieldError]) -> str | None:
    value = payload.get(field)
    if _is_missing(value):
        errors.append(FieldError(field=field, code="missing", message=f"{field} is required"))
        return None
    return str(value)


def _required_int(payload: Mapping[str, Any], field: str, errors: list[FieldError]) -> int | None:
    value = payload.get(field)
    if _is_missing(value):
        errors.append(FieldError(field=field, code="missing", message=f"{field} is required"))
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(FieldError(field=field, code="type", message=f"{field} must be an integer"))
        return None


def _required_decimal(
    payload: Mapping[str, Any],
    field: str,
    errors: list[FieldError],
    *,
    non_negative: bool = False,
) -> Decimal | None:
    value = payload.get(field)
    if _is_missing(value):
        errors.append(FieldError(field=field, code="missing", message=f"{field} is required"))
        return None
    try:
        result = Decimal(str(value))
    except Exception:
        errors.append(FieldError(field=field, code="type", message=f"{field} must be numeric"))
        return None
    if non_negative and result < 0:
        errors.append(
            FieldError(
                field=field, code="range", message=f"{field} must be non-negative",
                detail={"value": str(result)},
            )
        )
        return None
    return result


def _optional_decimal(payload: Mapping[str, Any], field: str) -> Decimal:
    value = payload.get(field, 0) or 0
    try:
        result = Decimal(str(value))
    except Exception:
        return Decimal("0")
    return max(Decimal("0"), result)


def _optional_int(payload: Mapping[str, Any], field: str) -> int:
    value = payload.get(field, 0) or 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
