from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExtractedFields(BaseModel):
    """Structured extraction envelope for one patient utterance."""

    model_config = ConfigDict(extra="forbid")
    fields: dict[str, Any] = Field(default_factory=dict)
    detected_language: dict[str, Any] = Field(default_factory=dict)


class RequiredFieldPolicy(BaseModel):
    fields: tuple[str, ...] = ()

    def is_complete(self, extracted: ExtractedFields) -> bool:
        return bool(self.fields) and all(
            name in extracted.fields
            and extracted.fields[name] is not None
            and str(extracted.fields[name]).strip() != ""
            for name in self.fields
        )
