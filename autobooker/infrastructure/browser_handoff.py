import json
from typing import Any
from urllib.parse import urlparse

import structlog
from playwright.async_api import (
    Request,
    async_playwright,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from autobooker.application.dom_analyzer import DOMAnalyzerService
from autobooker.domain.models import SessionData

logger = structlog.get_logger(__name__)


class BrowserHandoffManager:
    """Kapselt Session-Injection, Auto-Recovery, Login und JS-Manipulationen."""

    def __init__(self, timeout_ms: float = 60000.0) -> None:
        self.timeout_ms = timeout_ms

    def _format_cookies_for_playwright(self, cookies: dict[str, str], url: str) -> list[Any]:
        domain = urlparse(url).netloc
        return [{"name": k, "value": v, "domain": domain, "path": "/"} for k, v in cookies.items()]

    async def take_over(self, session_data: SessionData, target_url: str) -> None:
        """Startet den Browser für den Live-Modus und übergibt an den User."""
        logger.info("browser_handoff_started", target_url=target_url)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
            context = await browser.new_context(no_viewport=True)

            pw_cookies = self._format_cookies_for_playwright(session_data.cookies, target_url)
            if pw_cookies:
                try:
                    await context.add_cookies(pw_cookies)
                except Exception as e:
                    logger.warning("cookie_injection_warning", error=str(e))

            page = await context.new_page()
            try:
                await page.goto(target_url, timeout=self.timeout_ms)
            except Exception as e:
                logger.warning("timeout_during_navigation", error=str(e))

            logger.warning("HANDOFF ACTIVE: Bitte übernehmen und Zahlung abschließen!")
            print("\n\a")
            await page.pause()
            await browser.close()

    async def explore_and_extract_session(
        self, start_url: str, session_data: SessionData
    ) -> SessionData:
        """Exploration mit linearem SSO-Login-Flow und Hard-Recovery."""
        logger.info("exploration_browser_started", url=start_url)
        captured_payloads: dict[str, Any] = {}

        async def sniff_requests(request: Request) -> None:
            if request.method in ["POST", "PUT", "PATCH"] and (post_data := request.post_data):
                key = f"{request.method}_{urlparse(request.url).path}"
                try:
                    captured_payloads[key] = json.loads(post_data)
                except json.JSONDecodeError:
                    captured_payloads[key] = post_data

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
            context = await browser.new_context(no_viewport=True)
            page = await context.new_page()
            page.on("request", sniff_requests)

            # 1. Schritt: Wir rufen direkt den Kurs auf (triggert den SSO Redirect)
            logger.info("navigating_to_target_to_trigger_login")
            await page.goto(start_url)

            # 2. Schritt: Smart Login (Nur wenn Zugangsdaten vorliegen)
            if session_data.username and session_data.password:
                user_sel = 'input#username, input[name="username"], input[type="email"]'
                pass_sel = 'input#password, input[name="password"], input[type="password"]'
                btn_sel = 'input#kc-login, button[type="submit"], input[type="submit"]'

                try:
                    # Wir warten max. 5s, ob der Server uns auf eine Login-Maske geworfen hat
                    await page.wait_for_selector(user_sel, timeout=5000, state="visible")
                    logger.info("login_page_detected_starting_autofill")

                    await page.fill(user_sel, session_data.username)
                    await page.fill(pass_sel, session_data.password)

                    # Klick und warten auf die Weiterleitung (bringt uns meist auf /de/home/)
                    async with page.expect_navigation(timeout=15000):
                        await page.click(btn_sel)

                    logger.info("auto_login_success")
                except PlaywrightTimeoutError:
                    logger.info("no_login_form_found_assuming_already_logged_in")
                except Exception as e:
                    logger.warning("auto_login_error", error=str(e))

            # 3. Schritt: Zwangsrückkehr zur Kursseite (Hard Recovery)
            if "course_block_id" not in page.url:
                logger.info("redirecting_back_to_course_page_from_sso_home")
                await page.goto(start_url)
                await page.wait_for_load_state("networkidle")

            # 4. Schritt: UI Entsperren & Exploration freigeben
            unlock_js = (
                "document.querySelectorAll('.customer_select, input[disabled]')"
                ".forEach(e => e.removeAttribute('disabled'));"
            )
            await page.evaluate(unlock_js)
            await context.add_init_script(f"setInterval(() => {{ {unlock_js} }}, 1000);")

            print("\n\a")
            logger.warning("EXPLORATION ACTIVE: Wenn fertig, auf 'Resume' klicken!")
            await page.pause()

            # 5. Schritt: Daten extrahieren
            analyzer = DOMAnalyzerService()
            discovered_options = await analyzer.extract_bookable_options(page)

            pw_cookies = await context.cookies()
            cookies_dict = {c["name"]: c["value"] for c in pw_cookies}

            return SessionData(
                cookies=cookies_dict,
                known_payloads=captured_payloads,
                discovered_options=discovered_options,
                dummy_url=session_data.dummy_url,
                live_url=session_data.live_url,
                poll_interval_ms=session_data.poll_interval_ms,
                username=session_data.username,
                password=session_data.password,
            )
