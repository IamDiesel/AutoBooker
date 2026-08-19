import asyncio
from types import TracebackType
from typing import Any

import httpx
import structlog

from autobooker.domain.models import SessionData

logger = structlog.get_logger(__name__)


class ApiRequestError(Exception):
    """Basis-Exception für alle API-Fehler."""

    pass


class BotDetectedError(ApiRequestError):
    """Wird geworfen, wenn Cloudflare/Datadome etc. mit 403 oder 429 antworten."""

    pass


class FastCheckoutApiClient:
    """
    Der asynchrone HTTP-Client für Versuch 1 (Golden Path).
    Verwaltet die Session (Cookies) und sendet High-Speed Requests.
    """

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = str(base_url).rstrip("/")

        # Standard-Header, um nicht sofort als Python-Script (httpx) erkannt zu werden.
        # In der Praxis rotierst Du hier User-Agents oder nutzt spezifische Headers des Ziel-Shops.
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        # Wir nutzen HTTP/2 für maximale Geschwindigkeit und Connection Pooling
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout),
            http2=True,
            follow_redirects=True,
        )

    async def __aenter__(self) -> "FastCheckoutApiClient":
        """Unterstützt das `async with` Pattern für sicheres Ressourcen-Management."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Schließt den Client und die TCP-Verbindungen sauber ab."""
        await self.client.aclose()

    def _check_response_for_bot_protection(self, response: httpx.Response) -> None:
        """Prüft, ob wir von einer Web Application Firewall (WAF) blockiert wurden."""
        if response.status_code in (403, 429):
            logger.warning(
                "bot_protection_triggered", status_code=response.status_code, url=str(response.url)
            )
            raise BotDetectedError(f"Vom Anti-Bot System blockiert: HTTP {response.status_code}")

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(
                "api_request_failed",
                status_code=response.status_code,
                response_body=response.text[:200],
            )
            raise ApiRequestError(f"HTTP Fehler: {e}") from e

    async def add_to_cart(self, product_id: str) -> None:
        """Legt den Artikel in den Warenkorb."""
        logger.info("api_add_to_cart_start", product_id=product_id)

        # HINWEIS: Endpoint und Payload variieren je nach Ziel-Shop.
        payload = {"product_id": product_id, "quantity": 1}

        try:
            response = await self.client.post("/api/cart/add", json=payload)
            self._check_response_for_bot_protection(response)
            logger.info("api_add_to_cart_success", status=response.status_code)
        except httpx.RequestError as e:
            logger.error("api_network_error", error=str(e))
            raise ApiRequestError(f"Netzwerkfehler beim Add-to-Cart: {e}") from e

    async def submit_checkout_info(self, checkout_payload: dict[str, Any]) -> None:
        """Sendet die Rechnungs- und Lieferadresse."""
        logger.info("api_submit_checkout_info_start")
        try:
            response = await self.client.post("/api/checkout/info", json=checkout_payload)
            self._check_response_for_bot_protection(response)
            logger.info("api_submit_checkout_info_success")
        except httpx.RequestError as e:
            raise ApiRequestError(f"Netzwerkfehler beim Checkout-Info: {e}") from e

    def extract_session_data(self) -> SessionData:
        """
        Extrahiert die gesammelten Cookies, um sie später an Playwright (den echten Browser)
        zu übergeben. Dies ist der Kern des "Handoff"-Mechanismus.
        """
        cookies_dict = dict(self.client.cookies)

        # Optional: Wenn der Shop CSRF-Token in den Headern nutzt,
        # würden wir sie hier ebenfalls extrahieren.

        logger.debug("session_data_extracted", cookie_count=len(cookies_dict))
        return SessionData(cookies=cookies_dict)

    async def submit_booking(
        self, endpoint_path: str, payload: dict[str, Any], max_retries: int = 5
    ) -> httpx.Response:
        """
        Sendet den Buchungs-Payload mit aggressivem Retry-Looping
        bei 5xx Server-Fehlern (Überlastung).
        """
        logger.info("api_submit_booking_start", endpoint=endpoint_path)

        for attempt in range(1, max_retries + 1):
            try:
                response = await self.client.post(endpoint_path, json=payload)

                # Wenn der Server wegen Überlastung crasht (500, 502, 503, 504),
                # sofort nochmal versuchen
                if response.status_code >= 500:
                    logger.warning(
                        "server_error_retry", status=response.status_code, attempt=attempt
                    )
                    await asyncio.sleep(0.2)  # 200 Millisekunden Pause vor dem nächsten Hammer
                    continue

                self._check_response_for_bot_protection(response)
                logger.info("api_submit_booking_success", status=response.status_code)
                return response

            except httpx.RequestError as e:
                logger.warning("network_error_retry", error=str(e), attempt=attempt)
                if attempt == max_retries:
                    raise ApiRequestError(
                        f"Netzwerkfehler nach {max_retries} Versuchen: {e}"
                    ) from e
                await asyncio.sleep(0.2)

        raise ApiRequestError(f"Server dauerhaft überlastet nach {max_retries} Versuchen.")
