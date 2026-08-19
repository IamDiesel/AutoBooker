import json

import httpx
import pytest
import respx

from autobooker.infrastructure.api_client import BotDetectedError, FastCheckoutApiClient


# @pytest.mark.asyncio teilt dem Test-Runner mit, dass dies eine asynchrone Funktion ist.
# @respx.mock aktiviert den Netzwerk-Intercepter für diesen Test.
@pytest.mark.asyncio
@respx.mock
async def test_add_to_cart_success() -> None:
    """Testet den erfolgreichen API-Aufruf (HTTP 200)."""

    # 1. Arrange (Vorbereiten)
    base_url = "https://mock-shop.com"
    target_product = "termin_xyz_123"

    # Wir fangen genau diesen POST-Request ab und zwingen ihn,
    # ein HTTP 200 (OK) als Antwort zurückzugeben.
    mock_route = respx.post(f"{base_url}/api/cart/add").mock(
        return_value=httpx.Response(200, json={"status": "success"})
    )

    # 2. Act (Ausführen)
    async with FastCheckoutApiClient(base_url) as client:
        await client.add_to_cart(target_product)

    # 3. Assert (Überprüfen)
    # Wurde der Request wirklich abgefeuert?
    assert mock_route.called
    assert mock_route.call_count == 1

    # Haben wir den richtigen Payload (JSON Body) gesendet?
    last_request = mock_route.calls.last.request
    payload = json.loads(last_request.content)
    assert payload["product_id"] == target_product
    assert payload["quantity"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_bot_protection_trigger() -> None:
    """Testet, ob ein HTTP 403 korrekt als BotDetectedError erkannt wird."""

    base_url = "https://mock-shop.com"
    target_product = "termin_xyz_123"

    # Wir simulieren eine Cloudflare-Blockade
    respx.post(f"{base_url}/api/cart/add").mock(
        return_value=httpx.Response(403, text="Cloudflare Blocked - Access Denied")
    )

    # Wir erwarten, dass der Client abbricht und genau diesen Fehler wirft
    async with FastCheckoutApiClient(base_url) as client:
        with pytest.raises(BotDetectedError) as exc_info:
            await client.add_to_cart(target_product)

        # Überprüfen, ob die Fehlermeldung unseren Erwartungen entspricht
        assert "Vom Anti-Bot System blockiert" in str(exc_info.value)
        assert "403" in str(exc_info.value)
