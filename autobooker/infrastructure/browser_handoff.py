import json
from typing import Any
from urllib.parse import urlparse

import structlog
from playwright.async_api import Request, async_playwright

from autobooker.domain.models import SessionData

logger = structlog.get_logger(__name__)


class BrowserHandoffManager:
    """
    Kapselt die Logik, um eine bestehende HTTP-Session (Cookies/Tokens) in einen
    sichtbaren Playwright-Browser zu injizieren und an den User zu übergeben,
    oder umgekehrt, um Sessions und Payloads manuell zu explorieren.
    """

    def __init__(self, timeout_ms: float = 60000.0) -> None:
        self.timeout_ms = timeout_ms

    def _format_cookies_for_playwright(
        self, cookies: dict[str, str], target_url: str
    ) -> list[dict[str, Any]]:
        """Formatiert das flache Cookie-Dict in das von Playwright benötigte Format."""
        domain = urlparse(target_url).netloc
        return [
            {"name": name, "value": value, "domain": domain, "path": "/"}
            for name, value in cookies.items()
        ]

    async def take_over(self, session_data: SessionData, target_url: str) -> None:
        """
        Startet den sichtbaren Browser, injiziert die Cookies, navigiert zur URL und pausiert.
        Wird für 'Versuch 1' und 'Versuch 2' (Live-Lauf) genutzt, um an Paypal zu übergeben.
        """
        logger.info("browser_handoff_started", target_url=target_url)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, args=["--start-maximized"])

            context = await browser.new_context(
                no_viewport=True,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0.0.0 Safari/537.36"
                ),
            )

            # 1. Session-Daten (Cookies) injizieren
            pw_cookies = self._format_cookies_for_playwright(session_data.cookies, target_url)
            if pw_cookies:
                await context.add_cookies(pw_cookies)
                logger.info("cookies_injected", count=len(pw_cookies))

            # 2. Zielseite öffnen
            page = await context.new_page()
            logger.info("navigating_to_payment_gateway")

            try:
                await page.goto(target_url, timeout=self.timeout_ms)
            except Exception as e:
                logger.warning("timeout_during_navigation", error=str(e))

            # 3. MENSCHLICHE ÜBERGABE
            logger.warning("HANDOFF ACTIVE: Bitte im Browser übernehmen und Zahlung abschließen!")
            print("\n\a")  # Akustisches Signal

            await page.pause()

            logger.info("browser_handoff_completed_by_user")
            await browser.close()

    async def explore_and_extract_session(self, start_url: str) -> SessionData:
        """
        Öffnet einen sichtbaren Browser für die manuelle Exploration (Dry-Run).
        Snifft im Hintergrund Netzwerk-Traffic und extrahiert am Ende alle Cookies.
        """
        logger.info("exploration_browser_started", url=start_url)

        # Lokaler Speicher für unsere extrahierten Payloads
        captured_payloads: dict[str, Any] = {}

        async def sniff_requests(request: Request) -> None:
            """Event-Handler: Hört passiv im Hintergrund auf jeden ausgehenden Netzwerk-Request."""
            if request.method in ["POST", "PUT", "PATCH"]:
                post_data = request.post_data
                if post_data:
                    try:
                        # Versuche den Body als JSON zu parsen
                        payload = json.loads(post_data)

                        # Generiere einen eindeutigen Key, z.B. 'POST_/api/cart/add'
                        parsed_url = urlparse(request.url)
                        endpoint_key = f"{request.method}_{parsed_url.path}"

                        captured_payloads[endpoint_key] = payload
                        logger.info(
                            "json_payload_intercepted", method=request.method, path=parsed_url.path
                        )
                    except json.JSONDecodeError:
                        # War kein JSON. Ignorieren wir hier.
                        pass

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
            context = await browser.new_context(
                no_viewport=True,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            # --- NETZWERK-INTERCEPTION AKTIVIEREN ---
            page.on("request", sniff_requests)

            logger.info("Navigiere zur Zielseite. Bitte explorieren (z.B. Login durchführen).")
            await page.goto(start_url)

            print("\n\a")
            logger.warning(
                "EXPLORATION ACTIVE: Wenn fertig, klicke im Playwright Inspector auf 'Resume'."
            )

            await page.pause()

            # --- WISSENSEXTRAKTION (Cookies + Payloads) ---
            pw_cookies = await context.cookies()
            cookies_dict = {c["name"]: c["value"] for c in pw_cookies}

            logger.info(
                "exploration_completed",
                cookies_count=len(cookies_dict),
                payloads_found=len(captured_payloads),
            )

            return SessionData(cookies=cookies_dict, known_payloads=captured_payloads)
