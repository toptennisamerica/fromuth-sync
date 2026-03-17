from __future__ import annotations

from collections import Counter
from typing import Dict, List, Set

from src.content.generator import ContentGenerator
from src.logger import get_logger
from src.models import (
    ProductRecord,
    ShopifyProductMatch,
    ShopifyVariantMatch,
    SyncAction,
    SyncResults,
)
from src.shopify.client import ShopifyClient
from src.utils import clean_text, to_handle

logger = get_logger(__name__)


class SyncOrchestrator:
    def __init__(self, shopify: ShopifyClient, dry_run: bool = True) -> None:
        self.shopify = shopify
        self.dry_run = dry_run
        self.content_generator = ContentGenerator()

    def run(self, products: List[ProductRecord]) -> SyncResults:
        results = SyncResults()
        counters = Counter()

        sku_index, product_index = self.shopify.build_indexes()
        logger.info("Loaded %s Shopify SKUs", len(sku_index))

        for product in products:
            try:
                self._prepare_product(product)
                self._sync_product(product, sku_index, product_index, results, counters)
            except Exception as exc:
                logger.exception("Failed syncing %s", product.product_url)
                results.add_error(
                    message=str(exc),
                    product_title=product.resolved_title() if hasattr(product, "resolved_title") else product.title,
                    details={"product_url": product.product_url},
                )
                counters["errors"] += 1

        results.summary = dict(counters)
        return results

    def _prepare_product(self, product: ProductRecord) -> None:
        product.vendor = product.resolved_vendor() if hasattr(product, "resolved_vendor") else (product.vendor or product.brand)
        product.normalized_title = self._normalized_product_title(product)
        product.handle = to_handle(product.normalized_title or product.title or product.handle)

        for variant in product.variants:
            variant.price = variant.price or product.price

    def _normalized_product_title(self, product: ProductRecord) -> str:
        title = clean_text(product.title)

        title = re_sub(r"\s*\|\s*fall/winter\s+\d{4}\s*$", "", title)
        title = re_sub(r"\s*\|\s*spring/summer\s+\d{4}\s*$", "", title)
        title = re_sub(r"\s*-\s*men['’]s\s*$", "", title)
        title = re_sub(r"\s*-\s*women['’]s\s*$", "", title)
        title = re_sub(r"\s{2,}", " ", title).strip()

        lowered = product.title.lower()
        if "men" in lowered or "men's" in lowered or "mens" in lowered:
            suffix = " Men's Shoes"
        elif "women" in lowered or "women's" in lowered or "womens" in lowered:
            suffix = " Women's Shoes"
        else:
            suffix = " Shoes"

        return f"{title}{suffix}".strip()

    def _sync_product(
        self,
        product: ProductRecord,
        sku_index: Dict[str, ShopifyVariantMatch],
        product_index: Dict[str, ShopifyProductMatch],
        results: SyncResults,
        counters: Counter,
    ) -> None:
        content = self.content_generator.generate(product)
        matched_parent = self.shopify.find_product_ref(product, product_index)

        if matched_parent:
            self._update_parent_product(matched_parent, product, content, results, counters)

        existing_sku_found = any(v.sku in sku_index for v in product.variants)

        if not matched_parent:
            if existing_sku_found:
                results.add(
                    SyncAction(
                        sku="",
                        action="skip_create_product_existing_skus",
                        status="skipped",
                        product_title=product.resolved_title(),
                        notes="Skipped creating product because at least one SKU already exists in Shopify",
                    )
                )
                counters["skipped_existing_sku_product"] += 1
                return

            matched_parent = self._create_parent_product(
                product,
                content,
                sku_index,
                product_index,
                results,
                counters,
            )

            if self.dry_run:
                return

        scraped_skus: Set[str] = set()

        for variant in product.variants:
            scraped_skus.add(variant.sku)
            target_qty = variant.normalized_inventory()

            existing = sku_index.get(variant.sku)
            if existing:
                self._update_existing_variant(existing, product, variant, target_qty, results, counters)
                continue

            parent_ref = matched_parent or self.shopify.find_product_ref(product, product_index)
            if parent_ref:
                self._create_missing_variant(parent_ref, product, variant, sku_index, results, counters)
            else:
                results.add(
                    SyncAction(
                        sku=variant.sku,
                        action="unmatched_parent",
                        status="skipped",
                        product_title=product.resolved_title(),
                        notes="SKU not found and parent product match was unclear",
                    )
                )
                counters["skipped"] += 1

        if matched_parent and product.scrape_ok_for_zeroing:
            self._zero_missing_variants(
                matched_parent,
                scraped_skus,
                sku_index,
                product,
                results,
                counters,
            )

    def _update_parent_product(
        self,
        matched_parent: ShopifyProductMatch,
        product: ProductRecord,
        content,
        results: SyncResults,
        counters: Counter,
    ) -> None:
        if self.dry_run:
            results.add(
                SyncAction(
                    sku="",
                    action="update_product",
                    status="dry_run",
                    product_title=product.resolved_title(),
                    notes=f"Would update Shopify product {matched_parent.product_id} body, SEO, title, tags, and images",
                )
            )
        else:
            self.shopify.update_product_seo_and_body(matched_parent.product_id, product, content)
            self.shopify.update_product_images(matched_parent.product_id, product, content)

        counters["updated_products"] += 1

    def _create_parent_product(
        self,
        product: ProductRecord,
        content,
        sku_index: Dict[str, ShopifyVariantMatch],
        product_index: Dict[str, ShopifyProductMatch],
        results: SyncResults,
        counters: Counter,
    ) -> ShopifyProductMatch | None:
        if self.dry_run:
            results.add(
                SyncAction(
                    sku="",
                    action="create_product",
                    status="dry_run",
                    product_title=product.resolved_title(),
                    notes="Would create new draft Shopify product with Color and Size variants",
                )
            )
            counters["would_create_products"] += 1
            return None

        created = self.shopify.create_product(product, content)
        created_product = created["product"]
        product_id = int(created_product["id"])

        self.shopify.update_product_seo_and_body(product_id, product, content)
        self.shopify.update_product_images(product_id, product, content)

        variant_ids = []
        for created_variant in created_product.get("variants", []):
            sku = clean_text(created_variant.get("sku"))
            if not sku:
                continue

            inventory_item_id = created_variant.get("inventory_item_id")
            parsed_inventory_item_id = int(inventory_item_id) if inventory_item_id else None
            price = float(created_variant["price"]) if created_variant.get("price") not in (None, "") else None
            inventory_quantity = created_variant.get("inventory_quantity")
            parsed_inventory_quantity = int(inventory_quantity) if inventory_quantity not in (None, "") else None

            variant_ids.append(int(created_variant["id"]))
            sku_index[sku] = ShopifyVariantMatch(
                product_id=product_id,
                variant_id=int(created_variant["id"]),
                inventory_item_id=parsed_inventory_item_id,
                inventory_quantity=parsed_inventory_quantity,
                price=price,
                sku=sku,
                option1=clean_text(created_variant.get("option1")),
                option2=clean_text(created_variant.get("option2")),
            )

        for variant in product.variants:
            ref = sku_index.get(variant.sku)
            if ref and ref.inventory_item_id:
                self.shopify.set_inventory(ref.inventory_item_id, variant.normalized_inventory())

        matched_parent = ShopifyProductMatch(
            product_id=product_id,
            title=clean_text(created_product.get("title")),
            handle=clean_text(created_product.get("handle")),
            vendor=clean_text(created_product.get("vendor")),
            status=clean_text(created_product.get("status")),
            variant_ids=variant_ids,
        )

        if matched_parent.handle:
            product_index[matched_parent.handle] = matched_parent
        if matched_parent.title:
            product_index[matched_parent.title.lower()] = matched_parent

        results.add(
            SyncAction(
                sku="",
                action="create_product",
                status="success",
                product_title=product.resolved_title(),
                notes=f"Created draft Shopify product {product_id}",
            )
        )
        counters["created_products"] += 1
        return matched_parent

    def _update_existing_variant(
        self,
        existing: ShopifyVariantMatch,
        product: ProductRecord,
        variant,
        target_qty: int,
        results: SyncResults,
        counters: Counter,
    ) -> None:
        if variant.price is not None and (
            existing.price is None or round(existing.price, 2) != round(variant.price, 2)
        ):
            if self.dry_run:
                results.add(
                    SyncAction(
                        sku=variant.sku,
                        action="update_price",
                        status="dry_run",
                        old_price=existing.price,
                        new_price=variant.price,
                        product_title=product.resolved_title(),
                    )
                )
            else:
                self.shopify.update_variant_price(existing.variant_id, variant.price)

            counters["updated_prices"] += 1

        if self.dry_run:
            results.add(
                SyncAction(
                    sku=variant.sku,
                    action="update_inventory",
                    status="dry_run",
                    old_quantity=existing.inventory_quantity,
                    new_quantity=target_qty,
                    product_title=product.resolved_title(),
                )
            )
        else:
            if existing.inventory_item_id is not None:
                self.shopify.set_inventory(existing.inventory_item_id, target_qty)
            self.shopify.update_variant_inventory_policy(existing.variant_id, variant.available_to_order)

        counters["updated_inventory"] += 1

    def _create_missing_variant(
        self,
        parent_ref: ShopifyProductMatch,
        product: ProductRecord,
        variant,
        sku_index: Dict[str, ShopifyVariantMatch],
        results: SyncResults,
        counters: Counter,
    ) -> None:
        if self.dry_run:
            results.add(
                SyncAction(
                    sku=variant.sku,
                    action="create_variant",
                    status="dry_run",
                    product_title=product.resolved_title(),
                    new_quantity=variant.normalized_inventory(),
                    notes="Would append missing variant to existing Shopify product",
                )
            )
            counters["created_variants"] += 1
            return

        created_variant_payload = self.shopify.create_variant(parent_ref.product_id, product, variant)
        created_variant = created_variant_payload["variant"]

        inventory_item_id = created_variant.get("inventory_item_id")
        parsed_inventory_item_id = int(inventory_item_id) if inventory_item_id else None
        price = float(created_variant["price"]) if created_variant.get("price") not in (None, "") else None

        sku_index[variant.sku] = ShopifyVariantMatch(
            product_id=parent_ref.product_id,
            variant_id=int(created_variant["id"]),
            inventory_item_id=parsed_inventory_item_id,
            inventory_quantity=variant.normalized_inventory(),
            price=price,
            sku=variant.sku,
            option1=clean_text(created_variant.get("option1")),
            option2=clean_text(created_variant.get("option2")),
        )

        if parsed_inventory_item_id is not None:
            self.shopify.set_inventory(parsed_inventory_item_id, variant.normalized_inventory())

        self.shopify.update_variant_inventory_policy(int(created_variant["id"]), variant.available_to_order)

        results.add(
            SyncAction(
                sku=variant.sku,
                action="create_variant",
                status="success",
                product_title=product.resolved_title(),
                new_quantity=variant.normalized_inventory(),
                notes=f"Created missing variant under Shopify product {parent_ref.product_id}",
            )
        )
        counters["created_variants"] += 1

    def _zero_missing_variants(
        self,
        matched_parent: ShopifyProductMatch,
        scraped_skus: Set[str],
        sku_index: Dict[str, ShopifyVariantMatch],
        product: ProductRecord,
        results: SyncResults,
        counters: Counter,
    ) -> None:
        product_variants = self._shopify_variants_for_product(matched_parent.product_id, sku_index)

        for shopify_sku, ref in product_variants.items():
            if shopify_sku in scraped_skus:
                continue

            if self.dry_run:
                results.add(
                    SyncAction(
                        sku=shopify_sku,
                        action="zero_inventory",
                        status="dry_run",
                        old_quantity=ref.inventory_quantity,
                        new_quantity=0,
                        product_title=product.resolved_title(),
                        notes="Variant missing from current structured Fromuth data",
                    )
                )
            else:
                if ref.inventory_item_id is not None:
                    self.shopify.set_inventory(ref.inventory_item_id, 0)

            counters["zeroed_variants"] += 1

    def _shopify_variants_for_product(
        self,
        product_id: int,
        sku_index: Dict[str, ShopifyVariantMatch],
    ) -> Dict[str, ShopifyVariantMatch]:
        return {
            sku: ref
            for sku, ref in sku_index.items()
            if ref.product_id == product_id
        }


def re_sub(pattern: str, repl: str, text: str) -> str:
    import re
    return re.sub(pattern, repl, text, flags=re.I)