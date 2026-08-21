from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from autobooker.domain.strategy import AvailableOption, BookingStrategy


class RunMode(StrEnum):
    EXPLORATION = "exploration"
    LIVE_ATTEMPT_1 = "live_attempt_1"
    LIVE_ATTEMPT_2 = "live_attempt_2"


class BookingTarget(BaseModel):
    service_id: str
    preferred_date: str | None = None
    preferred_time: str | None = None


class SessionData(BaseModel):
    """Daten, die zwischen Exploration und Live-Run gespeichert werden."""

    cookies: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    csrf_token: str | None = None
    known_payloads: dict[str, Any] = Field(default_factory=dict)
    discovered_options: list[AvailableOption] = Field(default_factory=list)
    strategy: BookingStrategy = Field(default_factory=BookingStrategy)

    # GUI Persistenz & Settings
    dummy_url: str = ""
    live_url: str = ""
    poll_interval_ms: int = Field(default=500, ge=100)

    # Credentials für Auto-Login
    username: str = ""
    password: str = ""


class TaskConfig(BaseModel):
    target_url: HttpUrl
    target: BookingTarget
    mode: RunMode = Field(default=RunMode.EXPLORATION)
    timeout_seconds: float = Field(default=10.0, gt=0)


class BookingContext(BaseModel):
    config: TaskConfig
    session_data: SessionData = Field(default_factory=SessionData)
    last_error: str | None = None
