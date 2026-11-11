"""Bounded, typed inputs for the nine native workflows."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

WorkflowId = Literal[
    "leaduri", "facturi", "suport", "continut", "onboarding", "cv", "comenzi", "stoc", "reviewuri"
]


def valid_email(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or not re.fullmatch(r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+", value):
        raise ValueError("Adresa de email nu este validă.")
    if not value.isascii():
        raise ValueError("Folosește o adresă de email în format ASCII.")
    return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Contact(Input):
    name: str = Field(min_length=1, max_length=150)
    email: str
    _email = field_validator("email")(valid_email)


class Lead(Contact):
    message: str = Field(min_length=1, max_length=12000)


class Invoice(Contact):
    invoice_id: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="RON", pattern=r"^[A-Z]{3}$")
    due_date: date
    paid: bool = False


class Support(Lead):
    subject: str = Field(default="Solicitare", max_length=200)


class Content(Input):
    idea: str = Field(min_length=1, max_length=8000)
    audience: str = Field(min_length=1, max_length=500)
    objective: str = Field(min_length=1, max_length=500)


class Onboarding(Contact):
    started_at: date
    form_completed: bool = False


class Candidate(Contact):
    role: str = Field(min_length=1, max_length=200)
    cv_text: str = Field(default="", max_length=40000)


class Order(Contact):
    order_id: str = Field(min_length=1, max_length=120)
    total: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="RON", pattern=r"^[A-Z]{3}$")
    items: str = Field(min_length=1, max_length=6000)
    payment_status: str = Field(default="necunoscut", max_length=100)


class Stock(Input):
    sku: str = Field(min_length=1, max_length=120)
    product_name: str = Field(min_length=1, max_length=250)
    stock: float = Field(ge=0)
    threshold: float | None = Field(default=None, ge=0)


class Review(Contact):
    order_id: str = Field(min_length=1, max_length=120)
    delivered_at: date
    review_url: str = Field(max_length=2000)

    @field_validator("review_url")
    @classmethod
    def secure_link(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError(
                "Linkul pentru review trebuie să fie HTTPS, fără date de autentificare."
            )
        if any(c.isspace() for c in value):
            raise ValueError("Linkul pentru review nu poate conține spații.")
        return value


INPUTS: dict[str, type[Input]] = {
    "leaduri": Lead,
    "facturi": Invoice,
    "suport": Support,
    "continut": Content,
    "onboarding": Onboarding,
    "cv": Candidate,
    "comenzi": Order,
    "stoc": Stock,
    "reviewuri": Review,
}


class Configuration(Input):
    enabled: bool = False
    delivery_mode: Literal["review", "automatic"] = "review"
    company_name: str = Field(default="Compania ta", min_length=1, max_length=150)
    team_email: str = ""
    company_context: str = Field(default="", max_length=8000)
    stock_threshold: float = Field(default=5, ge=0)
    review_days: int = Field(default=7, ge=1, le=365)
    onboarding_reminder_days: int = Field(default=2, ge=1, le=90)
    onboarding_checkin_days: int = Field(default=7, ge=2, le=365)
    timezone: str = "Europe/Bucharest"

    @field_validator("team_email")
    @classmethod
    def team_address(cls, value: str) -> str:
        return valid_email(value) if value else ""

    @field_validator("timezone")
    @classmethod
    def zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Fus orar necunoscut.") from exc
        return value


class Event(Input):
    event_id: str = Field(min_length=1, max_length=160, pattern=r"^[\w.\-:]+$")
    data: dict[str, Any] = Field(default_factory=dict[str, Any])


class Draft(Input):
    recipient: str
    subject: str = Field(max_length=250)
    body: str = Field(max_length=24000)
    requires_review: bool = False
    _email = field_validator("recipient")(valid_email)

    @field_validator("subject", mode="before")
    @classmethod
    def single_line(cls, value: str) -> str:
        return " ".join(value.split())[:250]


class Plan(Input):
    stage: str
    summary: str
    steps: list[str]
    messages: list[Draft] = Field(default_factory=list)
    output: dict[str, Any] = Field(default_factory=dict[str, Any])
    skipped: bool = False
