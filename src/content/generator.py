from __future__ import annotations

import re
from collections import OrderedDict
from html import escape
from typing import Dict, List

from src.models import GeneratedContent, ProductRecord
from src.utils import clean_text


class ContentGenerator:
    def generate(self, product: ProductRecord) -> GeneratedContent:
        title = self._resolved_title(product)
        brand = clean_text(product.resolved_vendor() if hasattr(product, "resolved_vendor") else (product.vendor or product.brand))
        model = clean_text(product.model or self._model_from_title(title, brand))
        product_type = clean_text(product.product_type or "Tennis Shoes")

        body_html = self._build_body(product, title=title, brand=brand, model=model, product_type=product_type)
        seo_title = self._build_seo_title(title)
        meta_description = self._build_meta_description(product, title=title, brand=brand, model=model)
        tags = self._build_tags(product, brand=brand, model=model, product_type=product_type)
        image_alt_by_src = self._build_image_alts(product, title=title, brand=brand, model=model)

        return GeneratedContent(
            body_html=body_html,
            seo_title=seo_title,
            meta_description=meta_description,
            tags=tags,
            image_alt_by_src=image_alt_by_src,
        )

    def _resolved_title(self, product: ProductRecord) -> str:
        if hasattr(product, "resolved_title"):
            return clean_text(product.resolved_title())
        return clean_text(product.normalized_title or product.title)

    def _build_body(self, product: ProductRecord, title: str, brand: str, model: str, product_type: str) -> str:
        audience = self._audience_from_title(title)
        sport_text = self._sport_text(product)
        profile = self._play_profile(title, model)
        benefit_1, benefit_2 = self._benefit_pair(title, model)
        feature_bullets = self._feature_bullets(title, model, brand, sport_text)
        specs = self._spec_pairs(product, brand=brand, model=model, product_type=product_type, sport_text=sport_text)

        p1 = (
            f"<p><strong>{escape(title)}</strong> are a strong choice for {escape(audience)} "
            f"who want {escape(benefit_1)} and {escape(benefit_2)}. "
            f"Built for {escape(sport_text)}, this model is designed to help players move with confidence "
            f"during practice sessions, match play, and long days on court.</p>"
        )

        p2 = (
            f"<p>The <strong>{escape(brand)} {escape(model)}</strong> is ideal for players looking for "
            f"{escape(profile)}. Whether you play several times a week, compete regularly, or simply want "
            f"a dependable shoe for improving your movement and comfort, this model delivers the kind of "
            f"support and feel that helps you stay focused from the first point to the last.</p>"
        )

        features_html = "<h3>Key Features</h3><ul>" + "".join(
            f"<li>{item}</li>" for item in feature_bullets
        ) + "</ul>"

        specs_html = "<h3>Specifications</h3><ul>" + "".join(
            f"<li><strong>{escape(label)}:</strong> {escape(value)}</li>"
            for label, value in specs
            if value
        ) + "</ul>"

        return p1 + p2 + features_html + specs_html

    def _build_seo_title(self, title: str) -> str:
        title = clean_text(title)
        if len(title) <= 65:
            return title
        return title[:62].rstrip(" -|,") + "..."

    def _build_meta_description(self, product: ProductRecord, title: str, brand: str, model: str) -> str:
        audience = self._audience_from_title(title)
        desc = (
            f"Shop {brand} {model} for {audience.lower()} who want comfort, support, and dependable "
            f"court performance."
        )
        desc = clean_text(desc)
        if len(desc) <= 160:
            return desc
        return desc[:157].rstrip(" ,;:-") + "..."

    def _build_tags(self, product: ProductRecord, brand: str, model: str, product_type: str) -> List[str]:
        tags: List[str] = []
        title = self._resolved_title(product)

        tags.append(brand)
        if model:
            tags.append(model)
        if product.series:
            tags.append(product.series)
        tags.append(product_type)

        audience = self._audience_from_title(title)
        tags.append(audience)

        for tag in self._benefit_tags(title, model):
            tags.append(tag)

        colors = sorted({clean_text(v.color) for v in product.variants if clean_text(v.color)})
        if len(colors) == 1:
            tags.append(colors[0])

        deduped: List[str] = []
        seen = set()
        for tag in tags:
            clean_tag = clean_text(tag)
            if not clean_tag:
                continue
            key = clean_tag.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(clean_tag)
        return deduped

    def _build_image_alts(self, product: ProductRecord, title: str, brand: str, model: str) -> Dict[str, str]:
        alt_by_src: Dict[str, str] = {}
        seen_src = set()

        unique_colors = []
        seen_colors = set()
        for variant in product.variants:
            color = clean_text(variant.color)
            if color and color.lower() not in seen_colors:
                seen_colors.add(color.lower())
                unique_colors.append(color)

        color_index = 0
        for image in product.images:
            src = clean_text(image.src)
            if not src or src in seen_src:
                continue
            seen_src.add(src)

            color = unique_colors[color_index] if color_index < len(unique_colors) else ""
            if color:
                alt = f"{title} - {color}"
                color_index += 1
            else:
                alt = title

            alt_by_src[src] = alt

        return alt_by_src

    def _spec_pairs(
        self,
        product: ProductRecord,
        brand: str,
        model: str,
        product_type: str,
        sport_text: str,
    ) -> List[tuple[str, str]]:
        title = self._resolved_title(product)
        audience = self._audience_from_title(title)

        specs = [
            ("Brand", brand),
            ("Model", model),
            ("Category", audience if "Shoes" in audience else product_type),
            ("Court Type", self._court_type_from_title(title)),
            ("Use", sport_text),
        ]

        if product.series:
            specs.insert(2, ("Series", clean_text(product.series)))

        return specs

    def _benefit_pair(self, title: str, model: str) -> tuple[str, str]:
        text = f"{title} {model}".lower()

        if "enforce" in text or "tour" in text:
            return ("stability for aggressive movement", "responsive court feel")
        if "exceed" in text or "speed" in text:
            return ("lightweight comfort", "quick movement on court")
        if "court" in text:
            return ("everyday comfort", "reliable all-around performance")
        if "wave" in text:
            return ("supportive cushioning", "dependable traction")
        return ("comfort", "dependable court performance")

    def _play_profile(self, title: str, model: str) -> str:
        text = f"{title} {model}".lower()

        if "tour" in text or "enforce" in text:
            return "a more stable, performance-oriented feel for competitive players"
        if "exceed" in text or "light" in text or "speed" in text:
            return "a lighter, faster feel without giving up support"
        if "court" in text:
            return "a balanced mix of comfort, durability, and value"
        return "all-around court performance and lasting comfort"

    def _feature_bullets(self, title: str, model: str, brand: str, sport_text: str) -> List[str]:
        benefit_1, benefit_2 = self._benefit_pair(title, model)
        profile = self._play_profile(title, model)

        bullets = [
            f"<strong>{escape(benefit_1.capitalize())}</strong> for players who need confidence in every step",
            f"<strong>{escape(benefit_2.capitalize())}</strong> to support practice, league play, and match days",
            f"<strong>Built for {escape(sport_text)}</strong> with a fit and feel that works for regular court use",
            f"<strong>{escape(brand)} performance design</strong> focused on {escape(profile)}",
            "<strong>Versatile all-court option</strong> for players who want comfort, support, and everyday dependability",
        ]

        text = f"{title} {model}".lower()
        if "tour" in text or "enforce" in text:
            bullets[0] = "<strong>Stable performance feel</strong> for hard movers, strong pushes, and confident changes of direction"
            bullets[1] = "<strong>Supportive court response</strong> for players who want secure footing during aggressive play"
        elif "exceed" in text or "speed" in text:
            bullets[0] = "<strong>Lightweight movement</strong> for players who value speed, comfort, and easy transitions"
            bullets[1] = "<strong>Fast-feeling support</strong> for quick first steps and fluid movement around the court"
        elif "court" in text:
            bullets[0] = "<strong>Comfort-first design</strong> for everyday practice, match play, and frequent use"
            bullets[1] = "<strong>Reliable support</strong> for players who want a steady, easy-to-wear court shoe"

        return bullets

    def _benefit_tags(self, title: str, model: str) -> List[str]:
        text = f"{title} {model}".lower()
        tags: List[str] = []

        if "tour" in text or "enforce" in text:
            tags.extend(["Stability", "Match Play", "Competitive"])
        elif "exceed" in text or "speed" in text:
            tags.extend(["Lightweight", "Speed", "Quick Movement"])
        elif "court" in text:
            tags.extend(["Comfort", "All Court", "Everyday Play"])
        else:
            tags.extend(["Court Performance", "Comfort", "Support"])

        return tags

    def _audience_from_title(self, title: str) -> str:
        lowered = title.lower()
        if "men's" in lowered or "mens" in lowered:
            return "Men's Tennis Shoes"
        if "women's" in lowered or "womens" in lowered:
            return "Women's Tennis Shoes"
        return "Tennis Shoes"

    def _court_type_from_title(self, title: str) -> str:
        lowered = title.lower()
        if "ac" in lowered:
            return "All Court"
        if "clay" in lowered:
            return "Clay"
        return "All Court"

    def _sport_text(self, product: ProductRecord) -> str:
        specs_text = f"{clean_text(product.specifications_html)} {clean_text(product.description_html)}".lower()
        if "pickleball" in specs_text and "tennis" in specs_text:
            return "tennis and pickleball players"
        if "pickleball" in specs_text:
            return "pickleball players"
        return "tennis players"

    def _model_from_title(self, title: str, brand: str) -> str:
        clean_title = clean_text(title)
        if brand and clean_title.lower().startswith(brand.lower()):
            clean_title = clean_title[len(brand):].strip()

        clean_title = re.sub(r"\|\s*spring/summer\s+\d{4}", "", clean_title, flags=re.I).strip()
        clean_title = re.sub(r"\|\s*fall/winter\s+\d{4}", "", clean_title, flags=re.I).strip()
        clean_title = re.sub(r"\bmen['’]s shoes\b", "", clean_title, flags=re.I).strip()
        clean_title = re.sub(r"\bwomen['’]s shoes\b", "", clean_title, flags=re.I).strip()
        clean_title = re.sub(r"\bshoes\b", "", clean_title, flags=re.I).strip()
        clean_title = clean_title.strip("- ").strip()
        return clean_title