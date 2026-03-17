from __future__ import annotations

import re
from typing import Tuple

from src.utils import clean_text


def infer_series_and_model(title: str, brand: str) -> Tuple[str, str]:
    cleaned = clean_text(title)
    brand_clean = clean_text(brand)
    title_wo_brand = cleaned
    if brand_clean and cleaned.lower().startswith(brand_clean.lower()):
        title_wo_brand = clean_text(cleaned[len(brand_clean):])

    parts = re.split(r"\s+-\s+|\(|\)", title_wo_brand)
    base = clean_text(parts[0])

    tokens = base.split()
    series = ""
    if len(tokens) >= 2:
        series = " ".join(tokens[:2])
    elif tokens:
        series = tokens[0]

    model = base
    return series, model
