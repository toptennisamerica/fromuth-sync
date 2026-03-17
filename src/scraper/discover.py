from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.logger import get_logger

logger = get_logger(__name__)


class ProductDiscoverer:
    def __init__(self, client):
        self.client = client

    def discover(self, start_urls: list[str], max_products: int | None = None) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()

        for start_url in start_urls:
            page_num = 1

            while True:
                page_url = self._page_url(start_url, page_num)
                logger.info("Discovering from %s", page_url)

                html = self.client.get_html(page_url)
                soup = BeautifulSoup(html, "lxml")

                product_urls = self._extract_product_urls(start_url, soup)
                new_urls = [u for u in product_urls if u not in seen]

                for url in new_urls:
                    seen.add(url)
                    found.append(url)
                    if max_products and len(found) >= max_products:
                        return found

                if not self._has_next_page(soup, page_num):
                    break

                page_num += 1

        return found

    def _extract_product_urls(self, base_url: str, soup: BeautifulSoup) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()

        card_selectors = [
            ".product",
            ".productCard",
            ".card",
            "[data-product-id]",
            ".productGrid .product",
            ".productGrid .card",
        ]

        cards = []
        for selector in card_selectors:
            cards.extend(soup.select(selector))

        # Fallback: some pages may wrap product cards differently
        if not cards:
            cards = soup.select("article, li")

        for card in cards:
            anchors = card.select("a[href]")
            for a in anchors:
                href = (a.get("href") or "").strip()
                if not href:
                    continue

                full_url = self._normalize_url(urljoin(base_url, href))
                if not self._is_product_url(full_url):
                    continue

                if full_url in seen:
                    continue

                seen.add(full_url)
                urls.append(full_url)
                break

        return urls

    def _is_product_url(self, url: str) -> bool:
        parsed = urlparse(url)

        if parsed.netloc and "fromuthtennis.com" not in parsed.netloc:
            return False

        path = parsed.path.rstrip("/").lower()
        if not path:
            return False

        parts = [p for p in path.split("/") if p]

        # Real product URLs on Fromuth are typically one-segment slugs
        # like /mizuno-wave-strike-ac-mens-fall-winter-2026/
        if len(parts) != 1:
            return False

        slug = parts[0]

        blocked_exact = {
            "shoes",
            "mens-shoes",
            "womens-shoes",
            "apparel",
            "mens-apparel",
            "womens-apparel",
            "accessories",
            "racquet-accessories",
            "bags",
            "balls",
            "grips",
            "paddles",
            "racquets",
            "string-types",
            "strings",
            "clearance",
            "specials-list",
            "sale",
            "brands",
            "sports",
            "team",
            "custom-apparel",
            "customer-service",
            "login.php",
            "cart.php",
            "wishlist.php",
            "account.php",
            "giftcertificates.php",
            "search.php",
        }
        if slug in blocked_exact:
            return False

        lowered_full = url.lower()
        blocked_contains = [
            "_bc_fsnf",
            "sort=",
            "page=",
            "search",
            "brand=",
            "allowcustomergroup",
            "/specials-list/",
            "/shoes/",
            "/apparel/",
            "/accessories/",
            "/bags/",
            "/racquets/",
            "/paddles/",
            "/balls/",
            "/grips/",
            "/strings",
            "/string-types/",
            "/clearance/",
        ]
        if any(token in lowered_full for token in blocked_contains):
            return False

        # Product slugs are usually descriptive and long enough
        if len(slug) < 12:
            return False

        return True

    def _normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        clean = parsed._replace(query="", fragment="")
        return clean.geturl().rstrip("/") + "/"

    def _page_url(self, start_url: str, page_num: int) -> str:
        if page_num == 1:
            return start_url

        sep = "&" if "?" in start_url else "?"
        return f"{start_url}{sep}page={page_num}"

    def _has_next_page(self, soup: BeautifulSoup, current_page: int) -> bool:
        next_page = str(current_page + 1)

        for a in soup.select("a[href]"):
            text = a.get_text(" ", strip=True)
            href = (a.get("href") or "").lower()

            if text == next_page:
                return True
            if f"page={current_page + 1}" in href:
                return True

        return False