# Milestone 2 - backend API (Role A)

Run exactly as in Milestone 1 (`uvicorn app.main:app --reload` from `backend/`).
The two new tables (`knowledge_base`, `ticket_responses`) are created automatically.
Interactive docs: http://localhost:8000/docs

## Flow for every new ticket
create ticket -> classify (ml/classifier.py) -> **retrieve + generate (rag/)** -> save a `ticket_responses` row -> log.

- A failure in retrieval or generation never loses the ticket (it is logged as "Resolution generation failed").
- If classification fails or returns "Unknown", the ticket stays `Open`, retrieval still runs across all
  categories, and the response is flagged `needs_human_review = true`.

## Contracts the backend calls (Roles B and C)
```
rag.retriever.search_kb(query, category=None, top_k=3) -> [{slug, title, category, score, content}]
rag.retriever.index_kb()                               -> int (articles indexed)
rag.pipeline.resolve(subject, description, category)   -> {response_text, steps, sources, articles,
                                                           confidence, mode, needs_human_review, trace, response_ms}
```
- If `rag/retriever.py` / `rag/pipeline.py` do not exist yet, a built-in keyword fallback is used.
  `GET /rag/stats` -> `rag_source` shows `built-in-stub` or `rag-package`.
- A stub module can set `IS_STUB = True` to be shown as "rag-package (stub)".
- Missing keys in the pipeline result are filled with safe defaults; confidence is clamped to 0..1.
- Results must be JSON-serialisable (numpy numbers are converted automatically).

## Endpoints
| Method | URL | Purpose |
|---|---|---|
| GET | /kb/articles?category=&q= | list articles (without content) |
| GET | /kb/articles/{id} | one article with content |
| POST | /kb/articles | add `{title, category, keywords, content}`: saved as data/kb/<category>/<slug>.md, stored, indexed |
| POST | /kb/reindex | re-read data/kb/**/*.md into the DB, then call `index_kb()` |
| GET | /kb/search?q=&category=&top_k= | `{query, results:[{article_id, slug, title, category, score, content}], rag_source}` |
| GET | /tickets/{id}/response | latest generated resolution (404 if none yet) |
| POST | /tickets/{id}/resolve | run retrieval + generation again (creates a new row) |
| GET | /rag/stats | counts, avg confidence, % needing review, avg response ms, `retrieval_metrics` |

- The KB table is also synced from the article files automatically when the server starts.
- `retrieval_metrics` is read from `data/retrieval_metrics.json` if Role B's evaluation script writes it
  (e.g. `{"hit_at_1": 0.7, "hit_at_3": 0.88}`).

## Response shape (GET /tickets/{id}/response)
```json
{
  "response_id": 1, "ticket_id": 1,
  "generated_response": "Hello, ...",
  "confidence_score": 0.82, "mode": "extractive", "needs_human_review": false, "response_ms": 41.5,
  "sources": [{"slug": "vpn-timeout", "title": "VPN connection timed out", "score": 0.91}],
  "steps": ["Check that ...", "Close the VPN client ..."],
  "articles": [{"slug": "vpn-timeout", "title": "...", "category": "VPN", "score": 0.91}],
  "trace": [{"step": "Ticket analysis & query generation", "ms": 1.2},
            {"step": "Knowledge base retrieval", "ms": 20.1},
            {"step": "Context augmentation", "ms": 0.3},
            {"step": "Response generation", "ms": 18.5}],
  "generated_at": "2026-10-29T10:00:00+05:30"
}
```

## Notes
- Existing Milestone 1 tables are untouched, so there is no need to drop the database.
- `response_ms` is measured by the backend around the whole retrieval + generation call (target: under 5 s).
- Bulk CSV upload (`POST /tickets/bulk`) now also generates a response per ticket, so it is slower with the real models.
