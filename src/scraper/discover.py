from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.logger import get_logger

logger = get_logger(__name__)


class ProductDiscoverer:
    def __init__(self, client):
        self.client = client
        self.max_pages_per_start_url = 8

    def discover(self, start_urls: list[str], max_products: int | None = None) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()

        for start_url in start_urls:
            page_num = 1

            while page_num <= self.max_pages_per_start_url:
                page_url = self._page_url(start_url, page_num)
                logger.info("Discovering from %s", page_url)

                html = self.client.get_html(page_url)
                soup = BeautifulSoup(html, "lxml")

                product_urls = self._extract_product_urls(start_url, soup)
                new_urls = [u for u in product_urls if u not in seen]

                logger.info(
                    "Found %s product URLs on page %s (%s new)",
                    len(product_urls),
                    page_num,
                    len(new_urls),
                )

                for url in new_urls:
                    seen.add(url)
                    found.append(url)
                    if max_products and len(found) >= max_products:
                        logger.info("Reached max_products=%s during discovery", max_products)
                        return found

                if not new_urls and page_num > 1:
                    logger.info("No new product URLs found on page %s, stopping pagination for this start URL", page_num)
                    break

                if not self._has_next_page(soup, page_num):
                    break

                page_num += 1

            if page_num > self.max_pages_per_start_url:
                logger.info(
                    "Stopped pagination for %s after hitting max_pages_per_start_url=%s",
                    start_url,
                    self.max_pages_per_start_url,
                )

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
            ".productGrid-item",
            ".productView",
            ".productList .product",
        ]

        cards = []
        for selector in card_selectors:
            cards.extend(soup.select(selector))

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

        # Safer fallback: only inspect likely product anchors, not every article/li
        if not urls:
            for a in soup.select("a[href]"):
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

        return urls

    def _is_product_url(self, url: str) -> bool:
        parsed = urlparse(url)

        if parsed.netloc and "fromuthtennis.com" not in parsed.netloc:
            return False

        path = parsed.path.rstrip("/").lower()
        if not path:
            return False

        parts = [p for p in path.split("/") if p]

        # Fromuth product URLs are typically a single slug path.
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
            "/strings/",
            "/string-types/",
            "/clearance/",
            "#",
        ]
        if any(token in lowered_full for token in blocked_contains):
            return False

        if len(slug) < 12:
            return False

        # Must look like a real product slug, not a generic page
        has_dash = "-" in slug
        if not has_dash:
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