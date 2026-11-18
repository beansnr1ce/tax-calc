"""Field-level parsing shared by the facts builder and other payload readers
(e.g. the projection's YTD block). Each parser appends a `FieldError` and
returns None on bad input."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import FieldError


def is_missing(value: Any) -> bool:
    """None, or a blank string."""
    return value is None or (isinstance(value, str) and value.strip() == "")


def parse_decimal(
    value: Any, field: str, errors: list[FieldError], *, non_negative: bool = False
) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        result = None
    if result is None or not result.is_finite():
        errors.append(FieldError(field=field, code="type", message=f"{field} must be numeric"))
        return None
    if non_negative and result < 0:
        errors.append(
            FieldError(
                field=field,
                code="range",
                message=f"{field} must be non-negative",
                detail={"value": str(result)},
            )
        )
        return None
    return result


def parse_whole_number(value: Any, field: str, errors: list[FieldError]) -> int | None:
    """A non-negative integer (a count)."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        result = None
    if result is None or not result.is_finite() or result != result.to_integral_value():
        errors.append(
            FieldError(field=field, code="type", message=f"{field} must be a whole number")
        )
        return None
    if result < 0:
        errors.append(
            FieldError(field=field, code="range", message=f"{field} must be non-negative")
        )
        return None
    return int(result)
