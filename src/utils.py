from __future__ import annotations

import json
import os
import re
from html import escape
from pathlib import Path
from typing import Iterable, List, Sequence
from urllib.parse import urljoin, urlparse, urlunparse


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def to_handle(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    cleaned = parsed._replace(fragment="")
    return urlunparse(cleaned)


def absolute_url(base_url: str, maybe_relative: str) -> str:
    return normalize_url(urljoin(base_url, maybe_relative))


_ALLOWED_SIZES = {f"{x:.1f}" for x in [7 + (i * 0.5) for i in range(15)]}


def normalize_size(raw: str) -> str:
    value = clean_text(raw)
    value = value.replace("US", "").replace("Men's", "").replace("W", "").strip()
    match = re.search(r"(\d+(?:\.5)?)", value)
    if not match:
        return value
    num = float(match.group(1))
    normalized = f"{num:.1f}"
    return normalized


def is_supported_size(size: str) -> bool:
    return size in _ALLOWED_SIZES


def parse_money(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"(-?\$?\d[\d,]*\.?\d*)", text.replace(",", ""))
    if not match:
        return None
    cleaned = match.group(1).replace("$", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_int(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"-?\d+", text.replace(",", ""))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def unique_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def write_json(path: str | Path, data: object) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def strip_html_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "")


def truncate_text(value: str, limit: int) -> str:
    value = clean_text(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def html_list(items: Sequence[str]) -> str:
    lis = "".join(f"<li>{escape(clean_text(item))}</li>" for item in items if clean_text(item))
    return f"<ul>{lis}</ul>" if lis else ""
