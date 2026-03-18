from __future__ import annotations

import atexit

import cloudscraper
from tenacity import retry, stop_after_attempt, wait_fixed
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

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

        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

        atexit.register(self.close)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def get_html(self, url: str) -> str:
        # Category / listing pages should stay on cloudscraper only.
        if not self._looks_like_product_url(url):
            response = self.session.get(
                url,
                timeout=(10, 20),
                allow_redirects=True,
            )
            response.raise_for_status()
            return response.text

        # First try the fast path with cloudscraper.
        response = self.session.get(
            url,
            timeout=(10, 20),
            allow_redirects=True,
        )
        response.raise_for_status()
        html = response.text

        # If the raw HTML already contains what we need, do NOT use Playwright.
        if self._html_has_variant_data(html):
            return html

        # Fallback to Playwright only when needed.
        return self._get_html_playwright(url)

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

    def _html_has_variant_data(self, html: str) -> bool:
        lowered = html.lower()

        signals = [
            '"@type":"productgroup"',
            '"@type": "productgroup"',
            '"sku"',
            "sectupcgrid",
            "upc-table",
            "productview-title",
            "sectdescription",
            "sectspect",
        ]
        return any(signal in lowered for signal in signals)

    def _ensure_browser(self) -> None:
        if self._browser and self._context and self._page:
            return

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 2200},
        )
        self._page = self._context.new_page()

    def _get_html_playwright(self, url: str) -> str:
        self._ensure_browser()
        assert self._page is not None

        page = self._page
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        try:
            page.locator(
                "button:has-text('Accept'), button:has-text('Got it'), button:has-text('I agree')"
            ).first.click(timeout=2000)
        except Exception:
            pass

        try:
            page.locator("#sectUpcGridBtn, #sectUpcGridSectBtn").first.click(timeout=2000)
        except Exception:
            pass

        try:
            page.wait_for_selector(
                "#sectUpcGrid, dd#sectDescription, dd#sectSpec, h1, .productView-title",
                timeout=5000,
            )
        except Exception:
            pass

        try:
            page.wait_for_function(
                """
                () => {
                    const hasGrid = document.querySelector('#sectUpcGrid');
                    const hasRows = document.querySelectorAll('table.upc-table tbody tr').length > 0;
                    const hasSku = document.body.innerText.toLowerCase().includes('sku');
                    return !!(hasGrid || hasRows || hasSku);
                }
                """,
                timeout=6000,
            )
        except Exception:
            pass

        page.wait_for_timeout(800)

        return page.content()

    def close(self) -> None:
        try:
            if self._page is not None:
                self._page.close()
        except Exception:
            pass
        finally:
            self._page = None

        try:
            if self._context is not None:
                self._context.close()
        except Exception:
            pass
        finally:
            self._context = None

        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        finally:
            self._browser = None

        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        finally:
            self._pw = None
