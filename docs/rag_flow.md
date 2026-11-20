# Person B retrieval flow

The knowledge base source of truth is `data/kb/<category>/<slug>.md`. The
indexer embeds the article title, category, keywords, and body with
`gemini-embedding-001` using `RETRIEVAL_DOCUMENT`, then upserts the normalized
768-dimensional vector to Pinecone in the configured namespace.

Ticket queries use the same model with `RETRIEVAL_QUERY`. Pinecone uses cosine
similarity. Results preserve Pinecone's raw cosine score, including negative
values, and are filtered by
`MIN_RELEVANCE`; a category-filtered query retries across all categories when
it returns no acceptable results.

The embedding API is called in small batches with bounded exponential backoff.
The retry loop is for transient API failures and rate limits; it is not an
unbounded wait and does not affect the model context window.

Required environment variables:

```text
GEMINI_API_KEY
PINECONE_API_KEY
PINECONE_INDEX_NAME
PINECONE_NAMESPACE=customer-support-kb
```

The client automatically creates the configured Pinecone index if it does not
exist, using dimension `768` and metric `cosine`. Re-embed all articles if the
embedding model or dimension changes.

Commands:

```text
python -m rag.seed_articles
python -m rag.index_kb
python -m rag.eval_retrieval
```

The PDF importer preserves existing Markdown by default. Use `--replace` only
when intentionally replacing the corpus. Use `--rebuild` when starting a new
Pinecone corpus so the namespace is cleared first. If Gemini quota interrupts a
run, resume from the last printed offset without clearing the namespace again:

```text
python -m rag.index_kb --rebuild
python -m rag.index_kb --start 248
```

The resume offset must match the last successful `Indexed N/... articles`
message. The delay is controlled by `RAG_INDEX_BATCH_DELAY_SECONDS` to avoid
free-tier per-minute limits; the daily Gemini embedding quota still applies.
Failed articles are recorded in `data/index_failures.jsonl`. Retry only those
articles with `python -m rag.index_kb --retry-failures`; deterministic slug IDs
make retries idempotent even when later batches already succeeded.

# Person C resolution generation flow

The resolution pipeline is implemented in `rag/pipeline.py`.

The public interface is:

`resolve(subject, description, category)`

The pipeline follows four stages:

1. **Analyze ticket:** Combines the subject, description, and category into a retrieval query. It removes common greetings and signatures.
2. **Retrieve articles:** Calls Person B's `search_kb(query, category, top_k=3)` interface to retrieve relevant knowledge-base articles.
3. **Add context:** Uses the best retrieved article as the context for response generation.
4. **Generate response:** Produces a structured support response using only the retrieved article's instructions.

## Confidence calculation

The pipeline calculates confidence using three factors:

- Top article relevance score (50%).
- Category match (30%).
- Score gap between the top two articles (20%).

Formula:

`confidence = (0.50 × top_score) + (0.30 × category_match) + (0.20 × score_gap)`

All factors are bounded between 0 and 1.

If only one article is returned, its second score is treated as 0.

## Human review and safety

Human review is required when:

- No acceptable article is retrieved.
- The best article contains no numbered troubleshooting steps.
- Confidence is below `CONFIDENCE_THRESHOLD`.
- The ticket category is missing or `Unknown`.

When human review is required, the pipeline returns a safe message asking a support engineer to review the ticket. It does not invent troubleshooting steps.

## Response structure

The default response includes:

- A greeting.
- The retrieved article title.
- Numbered troubleshooting steps.
- Escalation instructions, when available.
- Safety notes, when available.
- Source article title.

The pipeline returns `response_text`, `steps`, `sources`, `articles`, `confidence`, `mode`, `needs_human_review`, `trace`, and `response_ms`.

## Execution trace

The pipeline records the execution time of four stages:

- `analyze_ticket`
- `retrieve_articles`
- `add_context`
- `generate_response`

The total execution time is returned as `response_ms`.

## Response generation mode

The current implementation uses the default article-based response generation mode. It does not require a Gemini generation API call. Retrieval still requires Gemini embeddings and Pinecone credentials.

## Tests

Run the Role B and Role C tests:

`python -m pytest tests/test_rag.py tests/test_resolution_pipeline.py -v`
