import typing

import structlog
from transitions import EventData, Machine

logger = structlog.get_logger(__name__)


class BookingStateMachine:
    """
    Steuert den Ablauf der Terminbuchung.
    Berücksichtigt den Explorations-Modus (Dry-Run).
    """

    state: str

    STATES = [
        "IDLE",
        "PREPARING_SESSION",
        "MONITORING",
        "SELECTING_APPOINTMENT",
        "FILLING_USER_DATA",
        "DRY_RUN_STOP",
        "HANDOFF_TO_PAYMENT",
        "COMPLETED",
        "FAILED",
    ]

    # --- Type Stubs für mypy und VS Code Autocomplete ---
    # Diese Methoden existieren nur für den Type-Checker. Zur Laufzeit generiert
    # 'transitions' diese automatisch.
    if typing.TYPE_CHECKING:

        def start(self) -> None: ...
        def session_ready(self) -> None: ...
        def slot_found(self) -> None: ...
        def slot_reserved(self) -> None: ...
        def stop_dry_run(self) -> None: ...
        def proceed_to_payment(self) -> None: ...
        def payment_done(self) -> None: ...
        def fail(self, error: str = "") -> None: ...
        def trigger_fallback(self) -> None: ...

    def __init__(self) -> None:
        self.machine = Machine(
            model=self, states=BookingStateMachine.STATES, initial="IDLE", send_event=True
        )

        # -- Der lineare Ablauf --
        self.machine.add_transition(trigger="start", source="IDLE", dest="PREPARING_SESSION")
        self.machine.add_transition(
            trigger="session_ready", source="PREPARING_SESSION", dest="MONITORING"
        )
        self.machine.add_transition(
            trigger="slot_found", source="MONITORING", dest="SELECTING_APPOINTMENT"
        )
        self.machine.add_transition(
            trigger="slot_reserved", source="SELECTING_APPOINTMENT", dest="FILLING_USER_DATA"
        )

        # -- Die Verzweigung: Exploration vs. Live --
        self.machine.add_transition(
            trigger="stop_dry_run",
            source="FILLING_USER_DATA",
            dest="DRY_RUN_STOP",
            before="log_dry_run_success",
        )
        self.machine.add_transition(
            trigger="proceed_to_payment", source="FILLING_USER_DATA", dest="HANDOFF_TO_PAYMENT"
        )

        self.machine.add_transition(
            trigger="payment_done", source="HANDOFF_TO_PAYMENT", dest="COMPLETED"
        )
        self.machine.add_transition(trigger="fail", source="*", dest="FAILED", before="log_failure")

    def log_dry_run_success(self, event: EventData) -> None:
        logger.info("Exploration erfolgreich. System stoppt vor echter Buchung.")

    def log_failure(self, event: EventData) -> None:
        error_msg = event.kwargs.get("error", "Kein expliziter Fehler")
        source = event.transition.source if event.transition else "UNKNOWN"
        logger.error("Fehler im Ablauf.", source_state=source, error=error_msg)
