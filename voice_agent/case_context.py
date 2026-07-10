"""Validated loading for case-specific runtime data."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .conversation_fsm import CaseContext


class CaseContextError(ValueError):
    """Raised when runtime case data cannot be loaded safely."""


class RuntimeCaseContext(BaseModel):
    """Strict external representation of one collections case."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(min_length=1)
    creditor_name: str = Field(min_length=1)
    customer_name: str = Field(min_length=1)
    locale: str = Field(min_length=1)
    disclosure_summary: str = Field(min_length=1)
    available_resolution_types: list[str]
    product_name: str | None = Field(default=None, min_length=1)
    amount_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    due_date: str | None = None
    reference: str | None = Field(default=None, min_length=1)
    metadata: dict[str, Any] | None = None

    @field_validator("available_resolution_types")
    @classmethod
    def validate_resolution_types(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("resolution types must be non-empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("resolution types must be unique")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", value) for value in cleaned):
            raise ValueError("resolution types must be bounded snake_case identifiers")
        return cleaned

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, value: str | None) -> str | None:
        if value:
            date.fromisoformat(value)
        return value

    def as_fsm_context(self) -> CaseContext:
        return cast(
            CaseContext,
            self.model_dump(exclude_none=True, mode="json"),
        )


def load_case_context(path_value: str | Path) -> CaseContext:
    """Read and strictly validate one runtime case JSON document."""

    path = Path(path_value)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CaseContextError(f"Case context file not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseContextError(f"Case context file is not valid JSON: {path}") from exc

    if not isinstance(raw, dict):
        raise CaseContextError(f"Case context must be a JSON object: {path}")
    try:
        parsed = RuntimeCaseContext.model_validate(raw)
    except (ValidationError, ValueError) as exc:
        count = exc.error_count() if isinstance(exc, ValidationError) else 1
        raise CaseContextError(
            f"Case context failed validation ({count} error(s)): {path}"
        ) from exc
    return parsed.as_fsm_context()
