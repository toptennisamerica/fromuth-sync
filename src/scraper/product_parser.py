from __future__ import annotations

import json
import re
from typing import List, Tuple

from bs4 import BeautifulSoup, Tag

from src.logger import get_logger
from src.models import ProductImage, ProductRecord, VariantRecord
from src.scraper.normalizers import infer_series_and_model
from src.utils import (
    absolute_url,
    clean_text,
    normalize_size,
    parse_money,
    to_handle,
)

logger = get_logger(__name__)


class ProductParser:
    MAX_IMAGES = 12

    def parse(self, product_url: str, html: str) -> ProductRecord:
        soup = BeautifulSoup(html, "lxml")

        title = self._extract_title(soup)
        brand = self._extract_brand(soup)
        price = self._extract_price(soup)
        description_html = self._extract_description_html(soup)
        specifications_html = self._extract_specifications_html(soup)
        images = self._extract_images(product_url, soup)

        gender = self._detect_gender(title)
        series, model = infer_series_and_model(title=title, brand=brand)

        record_kwargs = dict(
            product_url=product_url,
            handle=to_handle(title or product_url.rstrip("/").split("/")[-1]),
            title=title,
            brand=brand,
            series=series,
            model=model,
            product_type="Tennis Shoes",
            price=price,
            description_html=description_html,
            specifications_html=specifications_html,
            images=images,
        )

        try:
            record = ProductRecord(
                **record_kwargs,
                gender=gender,
            )
        except TypeError:
            record = ProductRecord(**record_kwargs)
            if hasattr(record, "gender"):
                setattr(record, "gender", gender)

        variants, inventory_found, backorder_detected, notes = self._extract_variants(soup, price)
        record.variants = variants
        record.inventory_found = inventory_found
        record.backorder_detected = backorder_detected
        record.notes.extend(notes)
        record.scrape_ok_for_zeroing = inventory_found and len(variants) > 0
        return record

    def _detect_gender(self, text: str) -> str:
        value = clean_text(text).lower()
        if not value:
            return ""

        if re.search(r"\bunisex\b", value):
            return "Unisex"

        if re.search(r"\bwomen'?s\b|\bwomen\b|\bwomens\b", value):
            return "Women's"

        if re.search(r"\bmen'?s\b|\bmen\b|\bmens\b", value):
            return "Men's"

        return ""

    def _extract_title(self, soup: BeautifulSoup) -> str:
        selectors = [
            "meta[property='og:title']",
            "h1",
            ".productView-title",
            "[data-product-title]",
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            if node.name == "meta":
                value = clean_text(node.get("content"))
            else:
                value = clean_text(node.get_text(" ", strip=True))
            if value:
                return value
        return ""

    def _extract_brand(self, soup: BeautifulSoup) -> str:
        for script in soup.select('script[type="application/ld+json"]'):
            raw = script.string or script.get_text(" ", strip=True)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue

                brand = item.get("brand")
                if isinstance(brand, dict):
                    name = clean_text(brand.get("name"))
                    if name:
                        return name.title()
                elif isinstance(brand, str):
                    name = clean_text(brand)
                    if name:
                        return name.title()

                manufacturer = item.get("manufacturer")
                if isinstance(manufacturer, dict):
                    name = clean_text(manufacturer.get("name"))
                    if name:
                        return name.title()
                elif isinstance(manufacturer, str):
                    name = clean_text(manufacturer)
                    if name:
                        return name.title()

        title = self._extract_title(soup)
        if title:
            first_word = clean_text(title.split()[0])
            if first_word and len(first_word) > 1:
                return first_word.title()

        selectors = [
            "[itemprop='brand']",
            ".productView-brand",
            ".brand",
            "a[href*='/brands/']",
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            value = clean_text(node.get_text(" ", strip=True))
            if value:
                return value.title()

        meta_keywords = soup.select_one("meta[name='keywords']")
        if meta_keywords:
            content = clean_text(meta_keywords.get("content"))
            if content:
                first = clean_text(content.split(",")[0])
                if first and " " not in first:
                    return first.title()

        return ""

    def _extract_price(self, soup: BeautifulSoup) -> float | None:
        selectors = [
            "meta[property='product:price:amount']",
            "[data-product-price-without-tax]",
            ".price--withoutTax",
            ".productView-price .price",
            ".price",
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            if not node:
                continue

            price = None
            if node.has_attr("content"):
                price = parse_money(str(node.get("content")))
            if price is None:
                price = parse_money(node.get_text(" ", strip=True))
            if price is not None:
                return price

        text = soup.get_text("\n", strip=True)
        for pattern in [
            r"Sale:\s*\$([0-9]+(?:\.[0-9]{2})?)",
            r"Cost:\s*\$([0-9]+(?:\.[0-9]{2})?)",
            r"\$([0-9]+(?:\.[0-9]{2})?)",
        ]:
            match = re.search(pattern, text, re.I)
            if match:
                return float(match.group(1))

        return None

    def _extract_description_html(self, soup: BeautifulSoup) -> str:
        node = soup.select_one("dd#sectDescription")
        if node:
            content = self._inner_html(node)
            if content:
                return content

        text = self._extract_section_text(
            soup,
            start_label="Product Description",
            stop_labels=["Specifications", "Inventory"],
        )
        return f"<p>{text}</p>" if text else ""

    def _extract_specifications_html(self, soup: BeautifulSoup) -> str:
        spec_items = soup.select("dd#sectSpec #specTable li")
        if spec_items:
            html_parts = ["<ul>"]
            for li in spec_items:
                name_node = li.select_one(".name")
                value_node = li.select_one(".value")

                name = clean_text(name_node.get_text(" ", strip=True)) if name_node else ""
                value = clean_text(value_node.get_text(" ", strip=True)) if value_node else ""

                if name and value:
                    html_parts.append(f"<li><strong>{name}</strong> {value}</li>")
                elif value:
                    html_parts.append(f"<li>{value}</li>")
            html_parts.append("</ul>")
            return "".join(html_parts)

        node = soup.select_one("dd#sectSpec")
        if node:
            content = self._inner_html(node)
            if content:
                return content

        text = self._extract_section_text(
            soup,
            start_label="Specifications",
            stop_labels=["Inventory"],
        )
        return f"<p>{text}</p>" if text else ""

    def _extract_section_text(self, soup: BeautifulSoup, start_label: str, stop_labels: List[str]) -> str:
        text = soup.get_text("\n", strip=True)
        start = text.find(start_label)
        if start == -1:
            return ""

        subset = text[start + len(start_label):]
        stop_positions = [subset.find(label) for label in stop_labels if subset.find(label) != -1]
        if stop_positions:
            subset = subset[: min(stop_positions)]

        return clean_text(subset)

    def _inner_html(self, node: Tag) -> str:
        return "".join(str(child) for child in node.contents).strip()

    def _extract_images(self, product_url: str, soup: BeautifulSoup) -> List[ProductImage]:
        title = self._extract_title(soup)

        jsonld_images = self._extract_images_from_jsonld(product_url, soup, title)
        if jsonld_images:
            return jsonld_images[: self.MAX_IMAGES]

        gallery_images = self._extract_images_from_gallery(product_url, soup, title)
        return gallery_images[: self.MAX_IMAGES]

    def _extract_images_from_jsonld(
        self,
        product_url: str,
        soup: BeautifulSoup,
        title: str,
    ) -> List[ProductImage]:
        results: List[ProductImage] = []
        seen_srcs = set()
        color_to_image = {}

        for script in soup.select('script[type="application/ld+json"]'):
            raw = script.string or script.get_text(" ", strip=True)
            if not raw:
                continue

            try:
                data = json.loads(raw)
            except Exception:
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") != "ProductGroup":
                    continue

                for variant in item.get("hasVariant", []) or []:
                    if not isinstance(variant, dict):
                        continue

                    color = clean_text(str(variant.get("color", ""))) or "Default"
                    color_key = color.lower()

                    image_nodes = variant.get("image") or []
                    if isinstance(image_nodes, dict):
                        image_nodes = [image_nodes]

                    for image_node in image_nodes:
                        if not isinstance(image_node, dict):
                            continue

                        src = clean_text(
                            image_node.get("contentUrl")
                            or image_node.get("url")
                            or ""
                        )
                        if not src:
                            continue

                        src = absolute_url(product_url, src)
                        if not self._is_valid_product_image(src):
                            continue

                        normalized_src = self._normalize_image_src(src)
                        if normalized_src in seen_srcs:
                            continue

                        if color_key not in color_to_image:
                            alt = clean_text(image_node.get("description")) or f"{title} - {color}"
                            color_to_image[color_key] = ProductImage(src=src, alt=alt or title)
                            seen_srcs.add(normalized_src)
                        break

        for _, image in color_to_image.items():
            results.append(image)

        return results

    def _extract_images_from_gallery(
        self,
        product_url: str,
        soup: BeautifulSoup,
        title: str,
    ) -> List[ProductImage]:
        images: List[ProductImage] = []
        seen = set()

        candidate_selectors = [
            ".productView-images img",
            ".productCarousel img",
            ".productView img",
            "[data-product-image] img",
            ".product-image img",
            "meta[property='og:image']",
        ]

        for selector in candidate_selectors:
            for node in soup.select(selector):
                if node.name == "meta":
                    src = clean_text(node.get("content"))
                    alt = title
                else:
                    src = (
                        node.get("src")
                        or node.get("data-src")
                        or node.get("data-lazy")
                        or node.get("data-original")
                        or ""
                    )
                    alt = clean_text(node.get("alt")) or title

                if not src:
                    continue

                src = absolute_url(product_url, src)
                if not self._is_valid_product_image(src):
                    continue

                normalized_src = self._normalize_image_src(src)
                if normalized_src in seen:
                    continue

                seen.add(normalized_src)
                images.append(ProductImage(src=src, alt=alt or title))

        return images

    def _normalize_image_src(self, src: str) -> str:
        src = clean_text(src)
        if not src:
            return ""
        return src.split("?", 1)[0].rstrip("/").lower()

    def _is_valid_product_image(self, src: str) -> bool:
        lowered = src.lower()

        blocked_terms = [
            "logo",
            "banner",
            "promo",
            "placeholder",
            "icon",
            "loading",
            "hero",
            "ad-",
            "sale-",
            "markdown",
        ]
        if any(term in lowered for term in blocked_terms):
            return False

        if "/products/" not in lowered and "/product_images/" not in lowered:
            return False

        return True

    def _extract_variants(
        self, soup: BeautifulSoup, product_price: float | None
    ) -> Tuple[List[VariantRecord], bool, bool, List[str]]:
        notes: List[str] = []

        jsonld_variants = self._extract_variants_from_jsonld(soup, product_price)
        if jsonld_variants:
            notes.append("Used ProductGroup JSON-LD as variant source.")
            return jsonld_variants, True, any(v.available_to_order for v in jsonld_variants), notes

        json_variants = self._extract_variants_from_json(soup, product_price)
        if json_variants:
            notes.append("Used generic JSON parser as fallback.")
            return json_variants, True, any(v.available_to_order for v in json_variants), notes

        fallback_variants = self._extract_variants_from_option_text(soup, product_price)
        if fallback_variants:
            notes.append("Used fallback option-text parser because structured variant data was not available.")
            return fallback_variants, True, any(v.available_to_order for v in fallback_variants), notes

        return [], False, False, notes

    def _extract_variants_from_jsonld(
        self, soup: BeautifulSoup, product_price: float | None
    ) -> List[VariantRecord]:
        variants: List[VariantRecord] = []

        for script in soup.select('script[type="application/ld+json"]'):
            raw = script.string or script.get_text(" ", strip=True)
            if not raw:
                continue

            try:
                data = json.loads(raw)
            except Exception:
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") != "ProductGroup":
                    continue

                has_variant = item.get("hasVariant") or []
                if not isinstance(has_variant, list):
                    continue

                for variant in has_variant:
                    if not isinstance(variant, dict):
                        continue

                    sku = clean_text(str(variant.get("sku", "")))
                    color = clean_text(str(variant.get("color", "")))
                    size_raw = clean_text(str(variant.get("size", "")))
                    mpn = clean_text(str(variant.get("mpn", "")))
                    upc = clean_text(str(variant.get("gtin", "")))

                    if not sku or not size_raw:
                        continue

                    offers = variant.get("offers") or []
                    offer = offers[0] if isinstance(offers, list) and offers else {}
                    availability = clean_text(str(offer.get("availability", ""))).lower()
                    variant_price = parse_money(str(offer.get("price", ""))) or product_price

                    stock = self._availability_to_stock(availability)
                    available_to_order = "preorder" in availability or "backorder" in availability

                    variants.append(
                        VariantRecord(
                            sku=sku,
                            color=color,
                            size_raw=size_raw,
                            size=normalize_size(size_raw),
                            mpn=mpn,
                            upc=upc,
                            stock=stock,
                            price=variant_price,
                            available_to_order=available_to_order,
                        )
                    )

        return self._dedupe_variants(variants)

    def _availability_to_stock(self, availability: str) -> int:
        availability = availability.lower()
        if "instock" in availability:
            return 999
        if "limitedavailability" in availability:
            return 999
        if "preorder" in availability or "backorder" in availability:
            return 999
        if "outofstock" in availability or "discontinued" in availability or "soldout" in availability:
            return 0
        return 0

    def _extract_variants_from_json(self, soup: BeautifulSoup, product_price: float | None) -> List[VariantRecord]:
        variants: List[VariantRecord] = []

        for script in soup.find_all("script"):
            content = script.string or script.get_text(" ", strip=True)
            if not content or ("sku" not in content.lower() and "variant" not in content.lower()):
                continue

            for match in re.finditer(r"(\{.*?\}|\[.*?\])", content, re.DOTALL):
                blob = match.group(1)
                if '"sku"' not in blob.lower():
                    continue
                try:
                    data = json.loads(blob)
                except Exception:
                    continue
                self._walk_json_for_variants(data, variants, product_price)

        return self._dedupe_variants(variants)

    def _walk_json_for_variants(self, data, variants: List[VariantRecord], product_price: float | None) -> None:
        if isinstance(data, dict):
            if "sku" in data:
                sku = clean_text(str(data.get("sku", "")))
                if sku:
                    size_raw = clean_text(str(data.get("size") or data.get("option2") or ""))
                    color = clean_text(str(data.get("color") or data.get("option1") or ""))
                    upc = clean_text(str(data.get("gtin") or data.get("upc") or data.get("barcode") or ""))
                    mpn = clean_text(str(data.get("mpn") or data.get("manufacturer") or ""))
                    availability_blob = json.dumps(data).lower()
                    stock = 999 if "instock" in availability_blob else 0

                    if size_raw:
                        variants.append(
                            VariantRecord(
                                sku=sku,
                                color=color,
                                size_raw=size_raw,
                                size=normalize_size(size_raw),
                                mpn=mpn,
                                upc=upc,
                                stock=stock,
                                price=product_price,
                                available_to_order=("backorder" in availability_blob or "preorder" in availability_blob),
                            )
                        )
            for value in data.values():
                self._walk_json_for_variants(value, variants, product_price)
        elif isinstance(data, list):
            for item in data:
                self._walk_json_for_variants(item, variants, product_price)

    def _extract_variants_from_option_text(self, soup: BeautifulSoup, product_price: float | None) -> List[VariantRecord]:
        text = soup.get_text("\n", strip=True)
        base_sku = self._extract_base_sku(text)
        if not base_sku:
            return []

        color = self._extract_selected_color(text) or ""
        size_tokens = self._extract_visible_sizes(text)
        if not size_tokens:
            return []

        available_to_order = bool(re.search(r"available to order|backorder", text, re.I))
        in_stock = bool(re.search(r"in stock\.?", text, re.I))
        stock_value = 999 if in_stock and not available_to_order else 0

        variants = []
        for size_raw in size_tokens:
            size = normalize_size(size_raw)
            if not size:
                continue

            sku = f"{base_sku}-{size}"
            color_code = self._color_code_guess(color)
            if color and color_code:
                sku = f"{base_sku}-{color_code}-{size}"

            variants.append(
                VariantRecord(
                    sku=sku,
                    color=color,
                    size_raw=size_raw,
                    size=size,
                    stock=stock_value,
                    price=product_price,
                    available_to_order=available_to_order,
                    notes=["Fallback variant built from visible option text; verify against structured source."],
                )
            )

        return self._dedupe_variants(variants)

    def _extract_base_sku(self, text: str) -> str:
        match = re.search(r"SKU:\s*([A-Za-z0-9\-_/]+)", text, re.I)
        return clean_text(match.group(1)) if match else ""

    def _extract_selected_color(self, text: str) -> str:
        match = re.search(r"Selected Color is\s*([A-Za-z0-9/()'\- ]+)", text, re.I)
        return clean_text(match.group(1)) if match else ""

    def _extract_visible_sizes(self, text: str) -> List[str]:
        match = re.search(
            r"Size:\s*\(Required\)\s*([0-9.\s]+)(?:In Stock\.|Available to Order|Product Description)",
            text,
            re.I | re.S,
        )
        blob = match.group(1) if match else text
        sizes = re.findall(
            r"\b(6(?:\.5)?|7(?:\.5)?|8(?:\.5)?|9(?:\.5)?|10(?:\.5)?|11(?:\.5)?|12(?:\.5)?|13(?:\.5)?|14(?:\.0)?|15(?:\.0)?)\b",
            blob,
        )
        return [clean_text(s) for s in sizes]

    def _color_code_guess(self, color: str) -> str:
        parts = [p for p in re.split(r"[^A-Za-z0-9]+", color) if p]
        if not parts:
            return ""
        return "/".join(part[:2].upper() for part in parts[:2])

    def _dedupe_variants(self, variants: List[VariantRecord]) -> List[VariantRecord]:
        deduped = {}
        for variant in variants:
            if not variant.sku:
                continue
            deduped[variant.sku] = variant
        return list(deduped.values())
