from __future__ import annotations

import time
from typing import Dict, List

import requests

from src.config import Settings
from src.logger import get_logger
from src.models import (
    GeneratedContent,
    ProductRecord,
    ShopifyProductMatch,
    ShopifyVariantMatch,
    VariantRecord,
)
from src.utils import clean_text, to_handle

logger = get_logger(__name__)


class ShopifyClient:
    API_VERSION = "2024-10"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = f"https://{settings.shopify_store_domain}/admin/api/{self.API_VERSION}"
        self.session = requests.Session()
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0

        # Proactive throttling: stay safely under Shopify REST limits.
        self._last_request_time = 0.0
        self._min_interval = 0.8

        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def _throttle(self) -> None:
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _get_valid_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < (self._access_token_expires_at - 60):
            return self._access_token

        token_url = f"https://{self.settings.shopify_store_domain}/admin/oauth/access_token"
        payload = {
            "client_id": self.settings.shopify_client_id,
            "client_secret": self.settings.shopify_client_secret,
            "grant_type": "client_credentials",
        }

        response = requests.post(
            token_url,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=self.settings.request_timeout,
        )
        response.raise_for_status()

        data = response.json()
        access_token = clean_text(data.get("access_token"))
        expires_in = int(data.get("expires_in", 0) or 0)

        if not access_token:
            raise RuntimeError("Shopify token exchange succeeded but no access_token was returned.")

        self._access_token = access_token
        self._access_token_expires_at = now + expires_in if expires_in > 0 else now + 23 * 3600
        self.session.headers["X-Shopify-Access-Token"] = access_token
        return access_token

    def _request(
        self,
        method: str,
        path: str,
        json_payload: dict | None = None,
        params: dict | None = None,
        max_attempts: int = 6,
    ):
        self._get_valid_access_token()
        url = f"{self.base_url}{path}"

        for attempt in range(1, max_attempts + 1):
            self._throttle()

            response = self.session.request(
                method,
                url,
                json=json_payload,
                params=params,
                timeout=self.settings.request_timeout,
            )

            if response.status_code == 401:
                self._access_token = None
                self._access_token_expires_at = 0.0
                self._get_valid_access_token()

                self._throttle()
                response = self.session.request(
                    method,
                    url,
                    json=json_payload,
                    params=params,
                    timeout=self.settings.request_timeout,
                )

            if response.status_code == 429:
                retry_after_header = clean_text(response.headers.get("Retry-After"))
                try:
                    retry_after = float(retry_after_header) if retry_after_header else 0.0
                except Exception:
                    retry_after = 0.0

                sleep_for = max(retry_after, min(2 ** attempt, 20))
                logger.warning(
                    "Shopify rate limit hit on %s %s. Sleeping %.1fs before retry %s/%s.",
                    method,
                    path,
                    sleep_for,
                    attempt,
                    max_attempts,
                )
                time.sleep(sleep_for)
                continue

            if 500 <= response.status_code < 600:
                sleep_for = min(2 ** attempt, 20)
                logger.warning(
                    "Shopify server error %s on %s %s. Sleeping %.1fs before retry %s/%s.",
                    response.status_code,
                    method,
                    path,
                    sleep_for,
                    attempt,
                    max_attempts,
                )
                time.sleep(sleep_for)
                continue

            if not response.ok:
                print("\n=== SHOPIFY ERROR ===")
                print("METHOD:", method)
                print("URL:", url)
                print("STATUS:", response.status_code)
                try:
                    print("RESPONSE JSON:", response.json())
                except Exception:
                    print("RESPONSE TEXT:", response.text)
                if json_payload is not None:
                    print("REQUEST PAYLOAD:", json_payload)
                response.raise_for_status()

            return response.json() if response.text else {}

        print("\n=== SHOPIFY ERROR ===")
        print("METHOD:", method)
        print("URL:", url)
        print("STATUS:", 429)
        if json_payload is not None:
            print("REQUEST PAYLOAD:", json_payload)
        raise RuntimeError(f"Shopify request failed after {max_attempts} attempts: {method} {path}")

    def _get(self, path: str, params: dict | None = None):
        return self._request("GET", path, params=params)

    def _post(self, path: str, payload: dict):
        return self._request("POST", path, json_payload=payload)

    def _put(self, path: str, payload: dict):
        return self._request("PUT", path, json_payload=payload)

    def list_products(self) -> List[dict]:
        products: List[dict] = []
        params = {
            "limit": 250,
            "fields": "id,title,handle,vendor,status,variants",
        }

        while True:
            data = self._get("/products.json", params=params)
            products.extend(data.get("products", []))

            next_page_info = self._extract_next_page_info(
                self.session.headers.get("Link", "")
            )

            # _request does not store response headers, so fetch Link header separately
            # by repeating the last request is wasteful. Instead, use the last response URL
            # pattern only when pagination exists in returned count.
            # Safer approach: inspect headers through a direct request wrapper.
            # Since Shopify pagination depends on Link header, use a dedicated direct call below.
            if len(data.get("products", [])) < 250:
                break

            page_info = self._fetch_next_page_info_for_products(params)
            if not page_info:
                break

            params = {
                "limit": 250,
                "page_info": page_info,
                "fields": "id,title,handle,vendor,status,variants",
            }

        return products

    def _fetch_next_page_info_for_products(self, params: dict) -> str | None:
        self._get_valid_access_token()
        url = f"{self.base_url}/products.json"

        self._throttle()
        response = self.session.get(
            url,
            params=params,
            timeout=self.settings.request_timeout,
        )

        if response.status_code == 401:
            self._access_token = None
            self._access_token_expires_at = 0.0
            self._get_valid_access_token()
            self._throttle()
            response = self.session.get(
                url,
                params=params,
                timeout=self.settings.request_timeout,
            )

        if response.status_code == 429:
            retry_after_header = clean_text(response.headers.get("Retry-After"))
            try:
                retry_after = float(retry_after_header) if retry_after_header else 2.0
            except Exception:
                retry_after = 2.0
            time.sleep(max(retry_after, 2.0))

            self._throttle()
            response = self.session.get(
                url,
                params=params,
                timeout=self.settings.request_timeout,
            )

        response.raise_for_status()
        return self._extract_next_page_info(response.headers.get("Link", ""))

    @staticmethod
    def _extract_next_page_info(link_header: str) -> str | None:
        if 'rel="next"' not in link_header:
            return None

        for part in link_header.split(","):
            if 'rel="next"' in part and "page_info=" in part:
                after = part.split("page_info=")[1]
                return after.split(">")[0]

        return None

    def build_indexes(self) -> tuple[Dict[str, ShopifyVariantMatch], Dict[str, ShopifyProductMatch]]:
        sku_index: Dict[str, ShopifyVariantMatch] = {}
        product_index: Dict[str, ShopifyProductMatch] = {}

        for product in self.list_products():
            product_id = int(product["id"])
            title = clean_text(product.get("title"))
            handle = clean_text(product.get("handle"))
            vendor = clean_text(product.get("vendor"))
            status = clean_text(product.get("status"))
            variant_ids: List[int] = []

            for variant in product.get("variants", []):
                sku = clean_text(variant.get("sku"))
                if not sku:
                    continue

                variant_ids.append(int(variant["id"]))

                inventory_quantity = variant.get("inventory_quantity")
                parsed_inventory_quantity = None
                if inventory_quantity not in (None, ""):
                    try:
                        parsed_inventory_quantity = int(inventory_quantity)
                    except Exception:
                        parsed_inventory_quantity = None

                price = None
                if variant.get("price") not in (None, ""):
                    try:
                        price = float(variant["price"])
                    except Exception:
                        price = None

                inventory_item_id = variant.get("inventory_item_id")
                parsed_inventory_item_id = int(inventory_item_id) if inventory_item_id else None

                sku_index[sku] = ShopifyVariantMatch(
                    variant_id=int(variant["id"]),
                    product_id=product_id,
                    inventory_item_id=parsed_inventory_item_id,
                    inventory_quantity=parsed_inventory_quantity,
                    price=price,
                    sku=sku,
                    option1=clean_text(variant.get("option1")),
                    option2=clean_text(variant.get("option2")),
                )

            product_ref = ShopifyProductMatch(
                product_id=product_id,
                title=title,
                handle=handle,
                vendor=vendor,
                status=status,
                variant_ids=variant_ids,
            )

            if handle:
                product_index[handle] = product_ref
            if title:
                product_index[title.lower()] = product_ref

        return sku_index, product_index

    def set_inventory(self, inventory_item_id: int, quantity: int) -> None:
        payload = {
            "location_id": int(self.settings.shopify_location_id),
            "inventory_item_id": int(inventory_item_id),
            "available": int(quantity),
        }
        self._post("/inventory_levels/set.json", payload)

    def update_variant_price(self, variant_id: int, new_price: float) -> None:
        payload = {
            "variant": {
                "id": int(variant_id),
                "price": f"{float(new_price):.2f}",
            }
        }
        self._put(f"/variants/{variant_id}.json", payload)

    def update_variant_inventory_policy(self, variant_id: int, allow_backorder: bool) -> None:
        payload = {
            "variant": {
                "id": int(variant_id),
                "inventory_policy": "continue" if allow_backorder else "deny",
            }
        }
        self._put(f"/variants/{variant_id}.json", payload)

    def create_product(self, product: ProductRecord, content: GeneratedContent) -> dict:
        variants = [self._variant_payload(product, variant) for variant in product.variants]
        unique_images = self._unique_product_images(product, content)

        create_images = unique_images[:1]

        payload = {
            "product": {
                "title": product.resolved_title(),
                "handle": product.handle or to_handle(product.resolved_title()),
                "body_html": content.body_html,
                "vendor": product.resolved_vendor(),
                "product_type": product.product_type,
                "status": product.status,
                "tags": ", ".join(content.tags),
                "options": [{"name": "Color"}, {"name": "Size"}],
                "variants": variants,
                "images": create_images,
                "metafields_global_title_tag": content.seo_title,
                "metafields_global_description_tag": content.meta_description,
            }
        }
        return self._post("/products.json", payload)

    def create_variant(self, product_id: int, product: ProductRecord, variant: VariantRecord) -> dict:
        payload = {
            "variant": self._variant_payload(
                product,
                variant,
                include_product_id=True,
                product_id=product_id,
            )
        }
        return self._post(f"/products/{product_id}/variants.json", payload)

    def update_product_seo_and_body(self, product_id: int, product: ProductRecord, content: GeneratedContent) -> None:
        payload = {
            "product": {
                "id": int(product_id),
                "title": product.resolved_title(),
                "handle": product.handle or to_handle(product.resolved_title()),
                "body_html": content.body_html,
                "vendor": product.resolved_vendor(),
                "product_type": product.product_type,
                "status": product.status,
                "tags": ", ".join(content.tags),
                "metafields_global_title_tag": content.seo_title,
                "metafields_global_description_tag": content.meta_description,
            }
        }
        self._put(f"/products/{product_id}.json", payload)

    def update_product_images(self, product_id: int, product: ProductRecord, content: GeneratedContent) -> None:
        unique_images = self._unique_product_images(product, content)
        if not unique_images:
            return

        time.sleep(1.5)

        existing = self._get(f"/products/{product_id}/images.json")
        existing_images = existing.get("images", []) if isinstance(existing, dict) else []

        existing_srcs = {
            self._normalize_image_src(clean_text(img.get("src")))
            for img in existing_images
            if clean_text(img.get("src"))
        }

        for image_payload in unique_images:
            normalized_src = self._normalize_image_src(clean_text(image_payload.get("src")))
            if not normalized_src or normalized_src in existing_srcs:
                continue

            self._post_product_image_with_retry(product_id, image_payload)
            existing_srcs.add(normalized_src)

    def _post_product_image_with_retry(self, product_id: int, image_payload: dict, max_attempts: int = 5) -> None:
        last_exc = None

        for attempt in range(1, max_attempts + 1):
            try:
                self._post(f"/products/{product_id}/images.json", {"image": image_payload})
                return
            except requests.HTTPError as exc:
                last_exc = exc
                status = exc.response.status_code if exc.response is not None else None

                if status == 409:
                    sleep_for = min(1.5 * attempt, 6)
                    logger.warning(
                        "Shopify says product %s is being modified. Sleeping %.1fs before retrying image upload.",
                        product_id,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
                    continue

                if status == 422:
                    logger.warning("Shopify rejected one image payload for product %s. Skipping it.", product_id)
                    return

                raise

        if last_exc:
            raise last_exc

    def _unique_product_images(self, product: ProductRecord, content: GeneratedContent) -> List[dict]:
        payloads: List[dict] = []
        seen = set()

        for image in product.images:
            src = clean_text(image.src)
            if not src:
                continue

            normalized_src = self._normalize_image_src(src)
            if normalized_src in seen:
                continue
            seen.add(normalized_src)

            payloads.append(
                {
                    "src": src,
                    "alt": content.image_alt_by_src.get(src, image.alt or product.resolved_title()),
                }
            )

        return payloads

    def _normalize_image_src(self, src: str) -> str:
        src = clean_text(src)
        if not src:
            return ""
        return src.split("?", 1)[0].rstrip("/").lower()

    def find_product_ref(
        self,
        product: ProductRecord,
        product_index: Dict[str, ShopifyProductMatch],
    ) -> ShopifyProductMatch | None:
        handle_key = clean_text(product.handle)
        if handle_key and handle_key in product_index:
            return product_index[handle_key]

        title_key = clean_text(product.resolved_title()).lower()
        if title_key and title_key in product_index:
            return product_index[title_key]

        alt_handle = to_handle(product.resolved_title())
        if alt_handle and alt_handle in product_index:
            return product_index[alt_handle]

        return None

    def _variant_payload(
        self,
        product: ProductRecord,
        variant: VariantRecord,
        include_product_id: bool = False,
        product_id: int | None = None,
    ) -> dict:
        payload = {
            "sku": variant.sku,
            "option1": variant.option1() or "Default",
            "option2": variant.option2() or variant.size_raw,
            "price": f"{float(variant.price or product.price or 0):.2f}",
            "barcode": variant.upc or "",
            "inventory_management": "shopify",
            "inventory_policy": "continue" if variant.available_to_order else "deny",
            "requires_shipping": bool(product.requires_shipping),
            "taxable": bool(product.taxable),
            "weight": float(product.weight),
            "weight_unit": product.weight_unit,
        }

        if include_product_id and product_id is not None:
            payload["product_id"] = int(product_id)

        return payload