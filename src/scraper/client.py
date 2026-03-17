from __future__ import annotations

import cloudscraper
from tenacity import retry, stop_after_attempt, wait_fixed
from playwright.sync_api import sync_playwright

from src.config import Settings


class FromuthHttpClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = cloudscraper.create_scraper(
            browser={
                "browser": "chrome",
                "platform": "darwin",
                "mobile": False,
            }
        )
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Upgrade-Insecure-Requests": "1",
                "Referer": "https://www.fromuthtennis.com/",
            }
        )

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def get_html(self, url: str) -> str:
        if self._looks_like_product_url(url):
            return self._get_html_playwright(url)

        response = self.session.get(
            url,
            timeout=(15, 45),
            allow_redirects=True,
        )
        response.raise_for_status()
        return response.text

    def _looks_like_product_url(self, url: str) -> bool:
        lowered = url.lower()
        blocked = [
            "_bc_fsnf",
            "page=",
            "/shoes/",
            "/apparel/",
            "/bags/",
            "/racquets/",
            "/paddles/",
            "/balls/",
            "/grips/",
            "/string-types/",
            "/clearance/",
            "/specials-list/",
        ]
        return not any(token in lowered for token in blocked)

    def _get_html_playwright(self, url: str) -> str:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 2200},
            )
            page = context.new_page()

            page.goto(url, wait_until="domcontentloaded", timeout=90000)

            try:
                page.locator("button:has-text('Accept'), button:has-text('Got it'), button:has-text('I agree')").first.click(timeout=5000)
            except Exception:
                pass

            try:
                page.locator("#sectUpcGridBtn, #sectUpcGridSectBtn").first.click(timeout=5000)
            except Exception:
                pass

            try:
                page.locator("#sectUpcGrid").first.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass

            try:
                page.wait_for_selector("#sectUpcGrid", timeout=15000)
            except Exception:
                pass

            try:
                page.wait_for_function(
                    """
                    () => {
                        const rows = document.querySelectorAll('table.upc-table tbody tr');
                        return rows && rows.length > 0;
                    }
                    """,
                    timeout=25000,
                )
            except Exception:
                pass

            try:
                page.wait_for_timeout(3000)
            except Exception:
                pass

            html = page.content()
            browser.close()
            return html