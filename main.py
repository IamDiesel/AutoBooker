import asyncio

import structlog
from pydantic import HttpUrl

from autobooker.application.orchestrator import BookingOrchestrator
from autobooker.domain.models import BookingTarget, RunMode, TaskConfig
from autobooker.infrastructure.session_store import SessionStore


def setup_logging() -> None:
    """
    Konfiguriert structlog so, dass wir während der Entwicklung
    eine schöne, bunte Terminal-Ausgabe (via rich) bekommen.
    """
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # 20 = INFO Level
        logger_factory=structlog.PrintLoggerFactory(),
    )


async def main() -> None:
    setup_logging()
    logger = structlog.get_logger(__name__)

    logger.info("system_booting", version="0.1.0")

    # 1. Konfiguration für den Test-Lauf definieren
    # Wir nutzen example.com, da wir hier gefahrlos einen "Warenkorb" simulieren können
    target = BookingTarget(
        service_id="termin_xyz_123", preferred_date="2026-12-20", preferred_time="10:00"
    )
    """
    config = TaskConfig(
        target_url=HttpUrl("https://example.com"),
        target=target,
        # WICHTIG: Wir setzen den Modus auf LIVE, damit der Playwright-Handoff am Ende auslöst!
        mode=RunMode.LIVE_ATTEMPT_1, 
        timeout_seconds=15.0
    )"""
    config = TaskConfig(
        # Eine harmlose Testseite mit einem echten Login-Formular
        target_url=HttpUrl("https://quotes.toscrape.com/login"),
        target=target,
        # WICHTIG: Wir wechseln in den Explorations-Modus!
        mode=RunMode.EXPLORATION,
        timeout_seconds=15.0,
    )

    # 2. Infrastruktur instanziieren
    store = SessionStore()  # Erstellt .data/session_state.json

    # 3. Application Layer (Orchestrator) starten
    orchestrator = BookingOrchestrator(config=config, store=store)

    logger.info("starting_workflow", target=config.target_url)

    try:
        await orchestrator.run()
        logger.info("workflow_completed_successfully")
    except Exception as e:
        logger.error("workflow_crashed", error=str(e))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nManuell durch Benutzer abgebrochen.")
