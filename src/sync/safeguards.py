from __future__ import annotations

from src.models import ProductRecord, VariantRecord


def should_zero_missing_variants(product: ProductRecord) -> bool:
    return bool(product.inventory_found and product.scrape_ok_for_zeroing and product.variants)


def target_quantity(variant: VariantRecord) -> int | None:
    if variant.available_to_order:
        return 999
    if variant.stock is None:
        return None
    return max(0, int(variant.stock))
