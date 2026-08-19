from pathlib import Path

import structlog

from autobooker.domain.models import SessionData

logger = structlog.get_logger(__name__)


class SessionStore:
    """
    Kapselt den Lese-/Schreibzugriff auf die Festplatte.
    Dependency Injection Ready.
    """

    def __init__(self, file_path: str = ".data/session_state.json") -> None:
        self.file_path = Path(file_path)
        # Stelle sicher, dass der Ordner existiert
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, session_data: SessionData) -> None:
        """Serialisiert das Pydantic-Modell und speichert es als JSON."""
        try:
            # model_dump_json ist die Pydantic v2 Methode für sichere Serialisierung
            json_data = session_data.model_dump_json(indent=2)
            self.file_path.write_text(json_data, encoding="utf-8")
            logger.info("session_saved", path=str(self.file_path))
        except Exception as e:
            logger.error("session_save_failed", error=str(e))
            raise

    def load(self) -> SessionData:
        """Lädt bestehende Daten von der Festplatte oder gibt eine leere Session zurück."""
        if not self.file_path.exists():
            logger.info("no_previous_session_found", path=str(self.file_path))
            return SessionData()

        try:
            raw_data = self.file_path.read_text(encoding="utf-8")
            # Validiere das JSON direkt wieder ins Pydantic-Modell
            data = SessionData.model_validate_json(raw_data)
            logger.info(
                "session_loaded",
                path=str(self.file_path),
                known_payloads=list(data.known_payloads.keys()),
            )
            return data
        except Exception as e:
            logger.warning("session_load_failed_creating_new", error=str(e))
            return SessionData()
