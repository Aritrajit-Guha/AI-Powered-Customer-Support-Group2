"""Markdown article parsing shared by indexing and validation."""

from __future__ import annotations

import re
from pathlib import Path


ALLOWED_CATEGORIES = {
    "Network",
    "VPN",
    "Software",
    "Hardware",
    "Password Reset",
    "Email",
    "Security",
}


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")[:120]


def parse_article(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").lstrip("\ufeff").replace("\r\n", "\n").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("article must start with a front-matter header")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("article front matter is not closed")
    metadata: dict[str, str] = {}
    for raw in lines[1:end]:
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        metadata[key.strip().lower()] = value.strip()
    body = "\n".join(lines[end + 1:]).strip()
    title = metadata.get("title", "")
    category = metadata.get("category", "")
    if not title:
        raise ValueError("missing title")
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f"unknown category: {category}")
    if len(body) < 20:
        raise ValueError("article body is too short")
    if not re.search(r"(?im)^steps:\s*$", body):
        raise ValueError("article is missing a Steps section")
    if not re.search(r"(?im)^escalate if:\s*.+$", body):
        raise ValueError("article is missing an Escalate if section")
    slug = slugify(path.stem)
    if not slug:
        raise ValueError("article filename must provide a slug")
    return {
        "slug": slug,
        "title": title,
        "category": category,
        "keywords": metadata.get("keywords", ""),
        "content": body,
    }


def iter_articles(kb_dir: Path) -> list[dict[str, str]]:
    articles = []
    seen: set[str] = set()
    for path in sorted(kb_dir.rglob("*.md")) if kb_dir.exists() else []:
        if path.name.lower() == "readme.md":
            continue
        article = parse_article(path)
        if article["slug"] in seen:
            raise ValueError(f"duplicate article slug: {article['slug']}")
        seen.add(article["slug"])
        articles.append(article)
    return articles
