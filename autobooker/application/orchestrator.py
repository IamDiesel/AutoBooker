import asyncio
import re
import time
from collections.abc import Callable
from pathlib import Path

import structlog

from autobooker.domain.models import BookingContext, RunMode, TaskConfig
from autobooker.domain.state_machine import BookingStateMachine
from autobooker.infrastructure.api_client import FastCheckoutApiClient
from autobooker.infrastructure.browser_handoff import BrowserHandoffManager
from autobooker.infrastructure.session_store import SessionStore

logger = structlog.get_logger(__name__)

__all__ = ["BookingOrchestrator"]


class BookingOrchestrator:
    def __init__(
        self,
        config: TaskConfig,
        store: SessionStore,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.progress_callback = progress_callback
        self.state_machine = BookingStateMachine()
        self.context = BookingContext(config=self.config, session_data=self.store.load())

        # Flag für den asynchronen Abbruch
        self._cancel_requested = False

    def cancel(self) -> None:
        """Signalisiert der laufenden Engine, dass sie abbrechen soll."""
        self._cancel_requested = True

    def _log_progress(self, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(message)
        logger.info("progress", message=message)

    async def run(self) -> None:
        mode = self.config.mode
        self._log_progress(f"Starte Orchestrator im Modus: {mode.value}")
        self.state_machine.start()
        self.state_machine.session_ready()

        try:
            if mode == RunMode.EXPLORATION:
                await self._run_interactive_exploration()
            else:
                await self._run_live_attempt()
        except asyncio.CancelledError:
            self._log_progress("[WARN] Vorgang durch den Nutzer abgebrochen!")
            raise
        except Exception as e:
            self.state_machine.fail(error=str(e))
            self.context.last_error = str(e)
            self.store.save(self.context.session_data)
            self._log_progress(f"[CRITICAL_ERROR] {e}")
            raise

    async def _run_interactive_exploration(self) -> None:
        self._log_progress("Starte Exploration. Automatischer Login läuft...")
        handoff_manager = BrowserHandoffManager()

        ext_session = await handoff_manager.explore_and_extract_session(
            str(self.config.target_url), self.context.session_data
        )

        self.context.session_data.cookies.update(ext_session.cookies)
        self.context.session_data.known_payloads.update(ext_session.known_payloads)
        self.context.session_data.discovered_options = ext_session.discovered_options

        self.state_machine.slot_found()
        self.state_machine.slot_reserved()
        self.state_machine.stop_dry_run()

        self.store.save(self.context.session_data)
        self._log_progress("Exploration erfolgreich abgeschlossen und gespeichert.")

    async def _run_live_attempt(self) -> None:
        match = re.search(r"course_block_id/(\d+)", str(self.config.target_url))
        target_id = match.group(1) if match else ""
        if not target_id:
            raise ValueError("Konnte keine Kurs-ID aus der URL extrahieren!")

        async with FastCheckoutApiClient(
            str(self.config.target_url), self.config.timeout_seconds
        ) as client:
            client.client.cookies.update(self.context.session_data.cookies)
            strategy = self.context.session_data.strategy

            if not strategy.actions:
                raise ValueError("Keine Strategie geladen! Bitte zuerst kalibrieren.")

            poll_path = str(self.config.target_url)
            checkout_path = strategy.target_url.replace("{TARGET_ID}", target_id)
            payload_string = strategy.generate_form_payload()

            self.state_machine.slot_found()
            poll_sec = self.context.session_data.poll_interval_ms / 1000.0
            self._log_progress(f"Scharf. Polling: {poll_sec}s. Ziel-ID: {target_id}")

            start_time = time.time()
            attempt = 0

            # --- DUAL-TRACK POLLING LOOP ---
            while time.time() - start_time < 3600:
                # Abbruchbedingung prüfen
                if self._cancel_requested:
                    raise asyncio.CancelledError("Polling vom User abgebrochen.")

                attempt += 1
                try:
                    poll_res = await client.client.get(poll_path)
                    html_text = poll_res.text.lower()

                    if 'disabled="disabled"' in html_text and "customer_select" in html_text:
                        self._log_progress(f"[Poll {attempt}] Slider deaktiviert. Warte...")
                        await asyncio.sleep(poll_sec)
                        continue

                    if "noch nicht buchbar" in html_text or "nicht buchbar" in html_text:
                        self._log_progress(f"[Poll {attempt}] Kurs gesperrt. Warte...")
                        await asyncio.sleep(poll_sec)
                        continue

                    self._log_progress(
                        f"[SUCCESS] Kurs offen (Versuch {attempt})! Sende Buchung..."
                    )

                    checkout_res = await client.submit_booking(
                        checkout_path, form_payload=payload_string, max_retries=1
                    )

                    # --- 🚨 TRACING: DER FLUGSCHREIBER 🚨 ---
                    trace_file = Path(".data") / f"checkout_trace_{target_id}.html"
                    trace_file.parent.mkdir(exist_ok=True)
                    trace_file.write_text(checkout_res.text, encoding="utf-8")
                    self._log_progress(f"[TRACE] Server-Antwort gesichert: {trace_file.name}")

                    if "mindestens einen teilnehmer aus" in checkout_res.text.lower():
                        raise ValueError("Warenkorb leer! Teilnehmer-ID wurde abgelehnt.")

                    self._log_progress("[SUCCESS] Kurs gebucht! Handoff initiieren...")
                    break

                except Exception as e:
                    self._log_progress(f"[ERROR] Polling-Fehler bei Versuch {attempt}: {e}")
                    await asyncio.sleep(poll_sec)

            self.state_machine.slot_reserved()
            self.state_machine.proceed_to_payment()

            base_match = re.match(r"(https?://[^/]+)", str(self.config.target_url))
            base_url = base_match.group(1) if base_match else str(self.config.target_url)
            cart_url = f"{base_url}/de/orders/cart"

            for cookie in client.client.cookies.jar:
                self.context.session_data.cookies[cookie.name] = cookie.value or ""

            handoff_manager = BrowserHandoffManager()
            await handoff_manager.take_over(self.context.session_data, cart_url)
            self.state_machine.payment_done()
