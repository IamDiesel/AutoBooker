from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class RunMode(StrEnum):
    EXPLORATION = "exploration"  # Dry-Run bis kurz vor Abschluss
    LIVE_ATTEMPT_1 = "live_attempt_1"
    LIVE_ATTEMPT_2 = "live_attempt_2"


class BookingTarget(BaseModel):
    """Repräsentiert den Ziel-Termin/die Leistung."""

    service_id: str
    preferred_date: str | None = None
    preferred_time: str | None = None


class SessionData(BaseModel):
    """Überlebenswichtige Daten, die zwischen Exploration und Live-Run gespeichert werden."""

    cookies: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    csrf_token: str | None = None
    known_payloads: dict[str, Any] = Field(
        default_factory=dict, description="In der Exploration gelernte Formular-Daten"
    )


class TaskConfig(BaseModel):
    """Konfiguration für den aktuellen Start des Bots."""

    target_url: HttpUrl
    target: BookingTarget
    mode: RunMode = Field(default=RunMode.EXPLORATION)
    timeout_seconds: float = Field(default=10.0, gt=0)


class BookingContext(BaseModel):
    """Wird durch die State Machine gereicht und ggfs. auf Festplatte persistiert."""

    config: TaskConfig
    session_data: SessionData = Field(default_factory=SessionData)
    last_error: str | None = None
