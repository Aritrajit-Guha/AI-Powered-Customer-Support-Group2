"""Knowledge base files  <->  database.

The Markdown files in data/kb/<category>/<slug>.md are the source of truth
(Role B writes and indexes them). This module copies them into the
Knowledge_Base table so the API can list and search them.

Article format (agreed with Role B):

    ---
    title: VPN connection timed out
    category: VPN
    keywords: vpn, timeout, cannot connect
    ---
    Symptoms: ...
    Steps:
    1. ...
"""
import re
from pathlib import Path

from sqlalchemy.orm import Session

from . import config
from .models import KnowledgeArticle


def slugify(text: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:120]) or "article"


def category_folder(category: str) -> str:
    return slugify(category)  # "Password Reset" -> "password-reset"


def normalize_category(value) -> str:
    v = str(value or "").strip().lower().replace("-", " ").replace("_", " ")
    for c in config.CATEGORIES:
        if c.lower() == v:
            return c
    raise ValueError(f"unknown category '{value}' (allowed: {config.CATEGORIES})")


def parse_markdown(text: str):
    """Split a '---' header (key: value lines) from the body."""
    lines = text.lstrip("\ufeff").replace("\r\n", "\n").split("\n")
    meta, body = {}, "\n".join(lines)
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                for raw in lines[1:i]:
                    if ":" in raw:
                        k, v = raw.split(":", 1)
                        meta[k.strip().lower()] = v.strip()
                body = "\n".join(lines[i + 1:])
                break
    return meta, body.strip()


def parse_article_file(path: Path) -> dict:
    meta, body = parse_markdown(path.read_text(encoding="utf-8"))
    if not meta.get("title"):
        raise ValueError("missing 'title' in the header")
    if len(body) < 20:
        raise ValueError("article body is too short")
    return {
        "slug": slugify(path.stem),
        "title": meta["title"],
        "category": normalize_category(meta.get("category")),
        "keywords": meta.get("keywords", ""),
        "content": body,
    }


def load_articles_from_files(db: Session, kb_dir=None) -> dict:
    """Upsert every article file into Knowledge_Base (matched by slug). Bad files are reported, not fatal."""
    kb_dir = Path(kb_dir or config.KB_DIR)
    result = {"kb_dir": str(kb_dir), "files_found": 0, "created": 0, "updated": 0, "errors": []}
    if not kb_dir.exists():
        result["errors"].append({"file": str(kb_dir), "error": "knowledge base folder does not exist yet"})
        return result

    seen = set()
    for path in sorted(kb_dir.rglob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        result["files_found"] += 1
        rel = str(path.relative_to(kb_dir))
        try:
            data = parse_article_file(path)
            if data["slug"] in seen:
                raise ValueError(f"duplicate slug '{data['slug']}' (same file name in two folders)")
            seen.add(data["slug"])
        except Exception as exc:
            result["errors"].append({"file": rel, "error": str(exc)})
            continue

        article = db.query(KnowledgeArticle).filter(KnowledgeArticle.slug == data["slug"]).first()
        if article:
            for k in ("title", "category", "keywords", "content"):
                setattr(article, k, data[k])
            result["updated"] += 1
        else:
            article = KnowledgeArticle(**data)
            db.add(article)
            result["created"] += 1
        db.flush()
        article.embedding_id = article.article_id
    db.commit()
    return result


def unique_slug(db: Session, title: str, kb_dir=None) -> str:
    kb_dir = Path(kb_dir or config.KB_DIR)
    base = slugify(title)
    slug, n = base, 2
    while (
        db.query(KnowledgeArticle).filter(KnowledgeArticle.slug == slug).first()
        or (kb_dir.exists() and any(kb_dir.rglob(f"{slug}.md")))
    ):
        slug = f"{base}-{n}"
        n += 1
    return slug


def write_article_file(category: str, slug: str, title: str, keywords: str, content: str, kb_dir=None) -> Path:
    kb_dir = Path(kb_dir or config.KB_DIR)
    folder = kb_dir / category_folder(category)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}.md"
    header = f"---\ntitle: {title}\ncategory: {category}\nkeywords: {keywords or ''}\n---\n"
    path.write_text(header + content.strip() + "\n", encoding="utf-8")
    return path
