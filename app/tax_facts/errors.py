from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class FieldError:
    field: str
    code: str
    message: str
    detail: Mapping[str, Any] = field(default_factory=dict)


class FactsError(ValueError):
    def __init__(self, errors: Sequence[FieldError]):
        self.errors = tuple(errors)
        super().__init__(f"{len(self.errors)} field error(s)")
