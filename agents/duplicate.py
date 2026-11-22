"""Optional duplicate-ticket detection backed by a separate vector namespace."""

from __future__ import annotations

import os
from typing import Any


def _namespace() -> str:
    return os.environ.get("PINECONE_TICKET_NAMESPACE", "supportpilot-ticket-vectors")


def find_duplicates(query: str, top_k: int = 3, min_score: float = 0.82) -> list[dict[str, Any]]:
    """Return similar indexed tickets; failures safely return no matches."""
    if not str(query or "").strip() or top_k <= 0:
        return []
    try:
        from rag.config import EMBEDDING_DIMENSION
        from rag.embeddings import RETRIEVAL_QUERY, embed_text
        from rag.pinecone_client import get_index

        response = get_index().query(
            vector=embed_text(query, RETRIEVAL_QUERY), top_k=top_k,
            include_metadata=True, namespace=_namespace(),
        )
        matches = response.get("matches", []) if isinstance(response, dict) else getattr(response, "matches", [])
        result = []
        for match in matches or []:
            score = float(match.get("score", 0.0) if isinstance(match, dict) else getattr(match, "score", 0.0))
            if score < min_score:
                continue
            metadata = match.get("metadata", {}) if isinstance(match, dict) else getattr(match, "metadata", {})
            result.append({"ticket_id": metadata.get("ticket_id"), "score": round(score, 4), "subject": metadata.get("subject", "")})
        return result
    except Exception:
        return []


def index_ticket(ticket_id: int, subject: str, description: str, category: str | None = None) -> bool:
    """Index a ticket for future duplicate checks; returns False when unavailable."""
    try:
        from rag.embeddings import RETRIEVAL_DOCUMENT, embed_text
        from rag.pinecone_client import get_index

        text = f"{subject or ''}\n{description or ''}"
        vector = embed_text(text, RETRIEVAL_DOCUMENT)
        get_index().upsert(vectors=[{"id": f"ticket-{ticket_id}", "values": vector, "metadata": {
            "ticket_id": ticket_id, "subject": subject or "", "category": category or "",
        }}], namespace=_namespace())
        return True
    except Exception:
        return False
