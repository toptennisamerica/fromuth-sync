from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    fromuth_start_urls: List[str]
    shopify_store_domain: str
    shopify_client_id: str
    shopify_client_secret: str
    shopify_location_id: str
    request_timeout: int
    max_retries: int
    user_agent: str
    dry_run: bool
    max_products: int

    @classmethod
    def from_env(cls) -> "Settings":
        start_urls = [
            item.strip()
            for item in os.getenv("FROMUTH_START_URLS", "").split(",")
            if item.strip()
        ]
        return cls(
            fromuth_start_urls=start_urls,
            shopify_store_domain=os.getenv("SHOPIFY_STORE_DOMAIN", "").strip(),
            shopify_client_id=os.getenv("SHOPIFY_CLIENT_ID", "").strip(),
            shopify_client_secret=os.getenv("SHOPIFY_CLIENT_SECRET", "").strip(),
            shopify_location_id=os.getenv("SHOPIFY_LOCATION_ID", "").strip(),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            user_agent=os.getenv(
                "USER_AGENT",
                "Mozilla/5.0 (compatible; FromuthScraper/1.0)",
            ).strip(),
            dry_run=_parse_bool(os.getenv("DRY_RUN"), default=True),
            max_products=int(os.getenv("MAX_PRODUCTS", "0")),
        )