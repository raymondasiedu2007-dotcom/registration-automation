from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


PROFILE_FIELDS = [
    "first_name",
    "last_name",
    "address_line1",
    "address_line2",
    "state_region",
    "city",
    "postal_code",
    "phone_number",
    "email",
    "country",
    "password",
]

SENSITIVE_FIELDS = {"phone_number", "email", "address_line1", "address_line2", "password"}


class AttemptStatus(str, Enum):
    STARTED = "started"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    MANUAL_REQUIRED = "manual_required"


@dataclass(slots=True)
class UserProfile:
    telegram_user_id: int
    first_name: str = ""
    last_name: str = ""
    address_line1: str = ""
    address_line2: str = ""
    state_region: str = ""
    city: str = ""
    postal_code: str = ""
    phone_number: str = ""
    email: str = ""
    country: str = ""
    password: str = ""

    def missing_required_fields(self) -> list[str]:
        return [field_name for field_name in PROFILE_FIELDS if not getattr(self, field_name, "").strip()]

    def is_complete(self) -> bool:
        return not self.missing_required_fields()

    def masked_dict(self) -> dict[str, str]:
        return {key: mask_value(key, getattr(self, key, "")) for key in PROFILE_FIELDS}

    def as_mapping(self) -> dict[str, str]:
        return {key: getattr(self, key, "") for key in PROFILE_FIELDS}


@dataclass(slots=True)
class SiteConfig:
    key: str
    name: str
    domain: str
    registration_url: str
    enabled: bool = True
    selectors: dict[str, str] = field(default_factory=dict)
    required_profile_fields: list[str] = field(default_factory=lambda: PROFILE_FIELDS.copy())
    submit_selector: str | None = None
    field_mappings: dict[str, str] = field(default_factory=dict)
    notes: str = ""
    status: str = "active"


@dataclass(slots=True)
class FieldMetadata:
    selector: str
    tag: str
    input_type: str | None = None
    name: str | None = None
    label: str | None = None
    placeholder: str | None = None
    aria_label: str | None = None
    nearby_text: str | None = None
    options: list[str] = field(default_factory=list)

    def to_ai_payload(self) -> dict[str, Any]:
        return {
            "selector": self.selector,
            "tag": self.tag,
            "input_type": self.input_type,
            "name": self.name,
            "label": self.label,
            "placeholder": self.placeholder,
            "aria_label": self.aria_label,
            "nearby_text": self.nearby_text,
            "options": self.options,
        }


def mask_value(field_name: str, value: str) -> str:
    if not value:
        return "(not set)"
    if field_name == "email" and "@" in value:
        prefix, domain = value.split("@", 1)
        return f"{prefix[:2]}***@{domain}"
    if field_name == "password":
        return "********"
    if field_name == "phone_number":
        digits = "".join(ch for ch in value if ch.isdigit())
        return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "***"
    if field_name in {"address_line1", "address_line2"}:
        return value[:4] + "***"
    return value


@dataclass(slots=True)
class RegistrationAttempt:
    id: int | None
    telegram_user_id: int
    site_key: str
    status: AttemptStatus
    started_at: datetime
    completed_at: datetime | None = None
    failure_reason: str | None = None
    manual_interventions: int = 0
