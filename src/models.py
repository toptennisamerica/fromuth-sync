from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ProductImage:
    src: str
    alt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VariantRecord:
    sku: str
    color: str
    size_raw: str
    size: str
    mpn: str = ""
    upc: str = ""
    stock: Optional[int] = None
    price: Optional[float] = None
    available_to_order: bool = False
    notes: List[str] = field(default_factory=list)

    def normalized_inventory(self) -> int:
        if self.stock is None:
            return 0
        return 1 if self.stock > 0 else 0

    def option1(self) -> str:
        return self.color.strip()

    def option2(self) -> str:
        return self.size.strip()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProductRecord:
    product_url: str
    handle: str
    title: str
    brand: str = ""
    series: str = ""
    model: str = ""
    product_type: str = "Tennis Shoes"
    vendor: str = ""
    normalized_title: str = ""
    status: str = "draft"
    track_inventory: bool = True
    weight: float = 3.0
    weight_unit: str = "lb"
    requires_shipping: bool = True
    taxable: bool = True
    price: Optional[float] = None
    description_html: str = ""
    specifications_html: str = ""
    images: List[ProductImage] = field(default_factory=list)
    variants: List[VariantRecord] = field(default_factory=list)
    scrape_ok_for_zeroing: bool = False
    inventory_found: bool = False
    backorder_detected: bool = False
    notes: List[str] = field(default_factory=list)

    def resolved_vendor(self) -> str:
        return (self.vendor or self.brand).strip()

    def resolved_title(self) -> str:
        return (self.normalized_title or self.title).strip()

    def option_names(self) -> List[str]:
        return ["Color", "Size"]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GeneratedContent:
    body_html: str
    seo_title: str
    meta_description: str
    tags: List[str]
    image_alt_by_src: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ShopifyVariantMatch:
    variant_id: int
    product_id: int
    inventory_item_id: Optional[int]
    inventory_quantity: Optional[int]
    price: Optional[float]
    sku: str
    option1: str = ""
    option2: str = ""


@dataclass
class ShopifyProductMatch:
    product_id: int
    title: str
    handle: str
    vendor: str = ""
    status: str = ""
    variant_ids: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SyncAction:
    sku: str
    action: str
    status: str
    notes: str = ""
    product_title: str = ""
    old_quantity: Optional[int] = None
    new_quantity: Optional[int] = None
    old_price: Optional[float] = None
    new_price: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SyncResults:
    actions: List[SyncAction] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)

    def add(self, action: SyncAction) -> None:
        self.actions.append(action)

    def bump(self, key: str, count: int = 1) -> None:
        self.summary[key] = self.summary.get(key, 0) + count

    def add_error(self, message: str, sku: str = "", product_title: str = "", details: Optional[Dict[str, Any]] = None) -> None:
        payload: Dict[str, Any] = {
            "message": message,
            "sku": sku,
            "product_title": product_title,
        }
        if details:
            payload["details"] = details
        self.errors.append(payload)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actions": [a.to_dict() for a in self.actions],
            "errors": self.errors,
            "summary": self.summary,
        }