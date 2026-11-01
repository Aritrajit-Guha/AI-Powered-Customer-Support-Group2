"""Bridge between the backend and the retrieval / generation code of Roles B and C.

Contracts (agreed by the whole team):

    rag.retriever.search_kb(query, category=None, top_k=3)
        -> [{"slug", "title", "category", "score", "content"}]
    rag.retriever.index_kb() -> number of articles indexed
    rag.pipeline.resolve(subject, description, category)
        -> {"response_text", "steps", "sources", "articles", "confidence",
            "mode", "needs_human_review", "trace", "response_ms"}

HOW IT WORKS
- If rag/retriever.py and rag/pipeline.py exist in the repo, they are used
  automatically (same idea as ml/classifier.py in Milestone 1).
- Until then, a simple built-in keyword search over the Knowledge_Base table
  answers, so the whole backend, the tests and the UI work today.
  Its labels are placeholders: it is NOT the real retrieval or generation.
"""
import importlib
import json
import re
import sys
import time
from pathlib import Path

from sqlalchemy.orm import Session

from .models import KnowledgeArticle

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.append(str(_ROOT))

FALLBACK_MIN_RELEVANCE = 0.15
FALLBACK_CONFIDENCE_THRESHOLD = 0.40


def _load(modname: str):
    try:
        return importlib.import_module(modname)
    except ModuleNotFoundError as exc:
        if exc.name and modname.startswith(exc.name):  # the module itself is not in the repo yet
            return None
        print(f"[rag] WARNING: {modname} found but a dependency is missing: {exc}")
        return None
    except Exception as exc:  # file exists but is broken
        print(f"[rag] WARNING: {modname} found but failed to load: {exc}")
        return None


_pipeline = _load("rag.pipeline")
_retriever = _load("rag.retriever")


def _label(mod, needed: str) -> str:
    if mod is not None and hasattr(mod, needed):
        return "rag-package (stub)" if getattr(mod, "IS_STUB", False) else "rag-package"
    return "built-in-stub"


def rag_source() -> dict:
    return {"retriever": _label(_retriever, "search_kb"), "pipeline": _label(_pipeline, "resolve")}


def _clean(obj):
    """Make sure the result can be stored as JSON (e.g. numpy floats)."""
    return json.loads(json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


# ----------------------------------------------------------------- search
_STOP = {"the", "and", "for", "with", "that", "this", "from", "have", "has", "not", "are", "was", "but",
         "can", "cant", "cannot", "please", "help", "hello", "thanks", "thank", "you", "your", "since",
         "when", "what", "how", "why", "all", "any", "out", "its", "get", "got", "very", "again", "still"}


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in _STOP}


def _fallback_search(db: Session, query: str, category=None, top_k=3) -> list:
    q = _tokens(query)
    if not q:
        return []
    rows = db.query(KnowledgeArticle)
    if category:
        rows = rows.filter(KnowledgeArticle.category == category)
    scored = []
    for a in rows.all():
        head = _tokens(f"{a.title} {a.keywords or ''}")
        body = _tokens(a.content)
        score = min(1.0, (2 * len(q & head) + len(q & (body - head))) / (2 * len(q)))
        if score >= FALLBACK_MIN_RELEVANCE:
            scored.append((score, a))
    scored.sort(key=lambda x: -x[0])
    return [
        {"slug": a.slug, "title": a.title, "category": a.category, "score": round(s, 3), "content": a.content}
        for s, a in scored[:top_k]
    ]


def search(db: Session, query: str, category=None, top_k=3) -> list:
    if hasattr(_retriever, "search_kb"):
        results = _clean(_retriever.search_kb(query, category=category, top_k=top_k))
    else:
        results = _fallback_search(db, query, category, top_k)
    slugs = [r.get("slug") for r in results if r.get("slug")]
    ids = {}
    if slugs:
        ids = {a.slug: a.article_id for a in db.query(KnowledgeArticle).filter(KnowledgeArticle.slug.in_(slugs))}
    out = []
    for r in results:
        out.append({
            "article_id": ids.get(r.get("slug")),
            "slug": r.get("slug"),
            "title": r.get("title"),
            "category": r.get("category"),
            "score": r.get("score"),
            "content": r.get("content"),
        })
    return out


def reindex(db: Session) -> dict:
    if hasattr(_retriever, "index_kb"):
        return {"indexed": int(_retriever.index_kb()), "source": _label(_retriever, "index_kb")}
    return {
        "indexed": 0,
        "source": "built-in-stub",
        "note": "No vector index yet (rag/retriever.py not found). The built-in keyword search reads the database directly.",
    }


# ---------------------------------------------------------------- resolve
def _extract_steps(content: str) -> list:
    return [m.group(2).strip() for m in re.finditer(r"^\s*(\d+)[.)]\s+(.+)$", content or "", re.M)]


def _extract_escalation(content: str):
    m = re.search(r"^\s*escalate if:\s*(.+)$", content or "", re.M | re.I)
    return m.group(1).strip() if m else None


def _fallback_resolve(db: Session, subject: str, description: str, category) -> dict:
    t0 = time.perf_counter()
    query = f"{subject or ''} {description or ''}".strip()
    t1 = time.perf_counter()
    results = _fallback_search(db, query, category, top_k=3)
    if category and not results:  # category may be wrong: retry everywhere
        results = _fallback_search(db, query, None, top_k=3)
    t2 = time.perf_counter()

    trace = lambda ms3, ms4: [  # noqa: E731
        {"step": "Ticket analysis & query generation", "ms": round((t1 - t0) * 1000, 2)},
        {"step": "Knowledge base retrieval", "ms": round((t2 - t1) * 1000, 2)},
        {"step": "Context augmentation", "ms": ms3},
        {"step": "Response generation", "ms": ms4},
    ]

    if not results:
        total = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "response_text": (
                "Hello,\n\nWe could not find a documented fix for this issue in our knowledge base. "
                "A support engineer will review your ticket and get back to you."
            ),
            "steps": [], "sources": [], "articles": [], "confidence": 0.0, "mode": "stub",
            "needs_human_review": True, "trace": trace(0.0, 0.0), "response_ms": total,
        }

    best = results[0]
    steps = _extract_steps(best["content"])
    escalate = _extract_escalation(best["content"])
    text = f'Hello,\n\nBased on our knowledge base article "{best["title"]}", please try these steps:\n\n'
    text += "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)) if steps else best["content"][:600]
    if escalate:
        text += f"\n\nIf the problem continues: {escalate}"
    text += f'\n\nSource: {best["title"]}'
    confidence = best["score"] * (1.0 if (category is None or best["category"] == category) else 0.8)
    total = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "response_text": text,
        "steps": steps,
        "sources": [{"slug": r["slug"], "title": r["title"], "score": r["score"]} for r in results[:1]],
        "articles": [{k: r[k] for k in ("slug", "title", "category", "score")} for r in results],
        "confidence": round(confidence, 3),
        "mode": "stub",
        "needs_human_review": confidence < FALLBACK_CONFIDENCE_THRESHOLD or not steps,
        "trace": trace(0.0, round(total - (t2 - t0) * 1000, 2)),
        "response_ms": total,
    }


def _normalize(raw) -> dict:
    """Make the pipeline output safe to store, whatever small differences it has."""
    if not isinstance(raw, dict):
        raise ValueError("rag.pipeline.resolve must return a dict")
    text = raw.get("response_text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("pipeline result has no response_text")
    try:
        conf = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
    except (TypeError, ValueError):
        conf = 0.0
    return _clean({
        "response_text": text,
        "steps": list(raw.get("steps") or []),
        "sources": list(raw.get("sources") or []),
        "articles": list(raw.get("articles") or []),
        "confidence": conf,
        "mode": str(raw.get("mode") or "rag"),
        "needs_human_review": bool(raw.get("needs_human_review", conf < FALLBACK_CONFIDENCE_THRESHOLD)),
        "trace": list(raw.get("trace") or []),
        "response_ms": raw.get("response_ms"),
    })


def resolve(db: Session, subject: str, description: str, category) -> dict:
    if hasattr(_pipeline, "resolve"):
        return _normalize(_pipeline.resolve(subject, description, category))
    return _normalize(_fallback_resolve(db, subject, description, category))
