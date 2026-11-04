"""Pinecone-backed knowledge-base retrieval."""

from __future__ import annotations

from . import config
from .embeddings import RETRIEVAL_QUERY, embed_text
from .pinecone_client import get_index


def _value(item, key, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _query(index, vector, top_k: int, category: str | None):
    kwargs = {
        "vector": vector,
        "top_k": top_k,
        "include_metadata": True,
        "namespace": config.PINECONE_NAMESPACE,
    }
    if category:
        kwargs["filter"] = {"category": {"$eq": category}}
    return index.query(**kwargs)


def _results(response) -> list[dict]:
    matches = _value(response, "matches", []) or []
    results = []
    for match in matches:
        metadata = _value(match, "metadata", {}) or {}
        # Preserve Pinecone's raw cosine similarity; negative values are valid.
        score = float(_value(match, "score", 0.0) or 0.0)
        if score < config.MIN_RELEVANCE:
            continue
        results.append(
            {
                "slug": str(metadata.get("slug", _value(match, "id", ""))),
                "title": str(metadata.get("title", "")),
                "category": str(metadata.get("category", "")),
                "score": round(score, 4),
                "content": str(metadata.get("content", "")),
            }
        )
    return results


def search_kb(query: str, category: str | None = None, top_k: int = 3) -> list[dict]:
    """Search the Pinecone index, falling back to an unfiltered search."""
    if not str(query or "").strip() or top_k <= 0:
        return []
    vector = embed_text(query, RETRIEVAL_QUERY)
    index = get_index()
    response = _query(index, vector, top_k, category)
    results = _results(response)
    if category and not results:
        results = _results(_query(index, vector, top_k, None))
    return results[:top_k]
