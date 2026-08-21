import logging
from pathlib import Path

import structlog

from autobooker.presentation.gui import AutoBookerApp


def setup_logging() -> None:
    """Konfiguriert duales Logging: Bunt in die Konsole, detailliert in eine Log-Datei."""
    # Stelle sicher, dass der .data Ordner existiert
    Path(".data").mkdir(exist_ok=True)

    # Standard-Logging konfigurieren (Schreibt in die Datei)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(".data/autobooker_run.log", encoding="utf-8"),
            logging.StreamHandler(),  # Für die Konsole
        ],
    )

    # Structlog auf das Standard-Logging umleiten
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def main() -> None:
    setup_logging()
    logger = structlog.get_logger(__name__)
    logger.info("launching_gui")

    # Startet den Tkinter Main Loop
    app = AutoBookerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
