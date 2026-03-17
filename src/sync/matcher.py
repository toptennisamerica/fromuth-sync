from __future__ import annotations

from src.models import ProductRecord
from src.shopify.client import ShopifyProductRef, ShopifyVariantRef


def match_parent_product(product: ProductRecord, product_index: dict[str, ShopifyProductRef]) -> ShopifyProductRef | None:
    if product.handle in product_index:
        return product_index[product.handle]
    title_key = (product.title or "").lower()
    if title_key in product_index:
        return product_index[title_key]
    return None
