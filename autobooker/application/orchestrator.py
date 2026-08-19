import asyncio

import structlog

from autobooker.domain.models import BookingContext, RunMode, TaskConfig
from autobooker.domain.state_machine import BookingStateMachine
from autobooker.infrastructure.api_client import FastCheckoutApiClient
from autobooker.infrastructure.browser_handoff import BrowserHandoffManager
from autobooker.infrastructure.session_store import SessionStore

logger = structlog.get_logger(__name__)


class BookingOrchestrator:
    def __init__(self, config: TaskConfig, store: SessionStore) -> None:
        self.config = config
        self.store = store
        self.state_machine = BookingStateMachine()
        self.context = BookingContext(config=self.config, session_data=self.store.load())

    async def run(self) -> None:
        mode = self.config.mode
        logger.info("orchestrator_started", mode=mode.value, target=self.config.target.service_id)

        self.state_machine.start()
        self.state_machine.session_ready()

        try:
            if mode == RunMode.EXPLORATION:
                await self._run_interactive_exploration()
            else:
                await self._run_live_attempt()

        except Exception as e:
            self.state_machine.fail(error=str(e))
            self.context.last_error = str(e)
            self.store.save(self.context.session_data)
            logger.error("orchestrator_failed_but_state_saved", error=str(e))
            raise

    async def _run_interactive_exploration(self) -> None:
        """Der Dry-Run: Browser öffnen, User manuell navigieren lassen, Daten abspeichern."""
        logger.info("starting_interactive_exploration")

        handoff_manager = BrowserHandoffManager()
        extracted_session = await handoff_manager.explore_and_extract_session(
            str(self.config.target_url)
        )

        # 1. Cookies updaten
        self.context.session_data.cookies.update(extracted_session.cookies)

        # 2. NEU: Die abgefangenen JSON-Payloads in den Kontext mergen
        self.context.session_data.known_payloads.update(extracted_session.known_payloads)

        self.state_machine.slot_found()
        self.state_machine.slot_reserved()
        self.state_machine.stop_dry_run()

        # Wissen auf Festplatte brennen (.data/session_state.json)
        self.store.save(self.context.session_data)
        logger.info("exploration_completed_and_saved")

    async def _run_live_attempt(self) -> None:
        """Der scharfe Lauf: High-Speed API mit injizierten Cookies und mutierten Payloads."""
        async with FastCheckoutApiClient(
            str(self.config.target_url), self.config.timeout_seconds
        ) as client:
            # 1. Cookies aus der Exploration injizieren
            client.client.cookies.update(self.context.session_data.cookies)

            # Warten auf den Release-Zeitpunkt
            await asyncio.sleep(0.5)
            self.state_machine.slot_found()

            target_id = self.config.target.service_id
            logger.info("reserving_slot_via_api", service_id=target_id)

            # 2. Payload laden (ACHTUNG: Den Key müssen wir nach der Exploration anpassen!)
            # Wir nehmen an, wir haben den Request-Pfad beim Sniffen gesehen:
            endpoint_key = "POST_/api/cart/add"

            if endpoint_key not in self.context.session_data.known_payloads:
                raise ValueError(f"Payload für '{endpoint_key}' fehlt in .data/session_state.json!")

            payload = self.context.session_data.known_payloads[endpoint_key]

            # 3. DYNAMISCHE MANIPULATION (Mutation)
            # HIER ersetzen wir die Dummy-ID durch die echte Ziel-ID.
            # (Der Key 'product_id' muss dem echten JSON des Shops entsprechen!)
            payload["product_id"] = target_id

            # 4. Abfeuern mit Retry-Looping
            endpoint_path = endpoint_key.split("_", 1)[
                1
            ]  # Macht aus 'POST_/api/cart/add' -> '/api/cart/add'
            await client.submit_booking(endpoint_path, payload)

            self.state_machine.slot_reserved()

            # 5. Finale Übergabe an den Nutzer
            self.state_machine.proceed_to_payment()
            logger.info("initiating_browser_handoff")

            self.context.session_data.cookies.update(client.client.cookies)
            handoff_manager = BrowserHandoffManager()
            await handoff_manager.take_over(self.context.session_data, str(self.config.target_url))

            self.state_machine.payment_done()
