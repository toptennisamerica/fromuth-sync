from __future__ import annotations

from typing import Iterable

from src.models import ProductRecord, SyncResults


def products_to_json(products: Iterable[ProductRecord]) -> list[dict]:
    return [product.to_dict() for product in products]


def sync_results_to_json(results: SyncResults) -> dict:
    return results.to_dict()
