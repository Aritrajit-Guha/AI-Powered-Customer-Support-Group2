# Person B retrieval flow

The knowledge base source of truth is `data/kb/<category>/<slug>.md`. The
indexer embeds the article title, category, keywords, and body with
`gemini-embedding-001` using `RETRIEVAL_DOCUMENT`, then upserts the normalized
768-dimensional vector to Pinecone in the configured namespace.

Ticket queries use the same model with `RETRIEVAL_QUERY`. Pinecone uses cosine
similarity. Results are clamped to `0.0..1.0` and filtered by
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

Create the Pinecone index with dimension `768` and metric `cosine` before
running the indexer. Re-embed all articles if the embedding model or dimension
changes.

Commands:

```text
python -m rag.seed_articles
python -m rag.index_kb
python -m rag.eval_retrieval
```

The PDF importer clears old article Markdown before writing the replacement
corpus. Use `--rebuild` when starting a new corpus so the Pinecone namespace is
cleared first. If Gemini quota interrupts a run, resume from the last printed
offset without clearing the namespace again:

```text
python -m rag.index_kb --rebuild
python -m rag.index_kb --start 248
```

The resume offset must match the last successful `Indexed N/... articles`
message. The delay is controlled by `RAG_INDEX_BATCH_DELAY_SECONDS` to avoid
free-tier per-minute limits; the daily Gemini embedding quota still applies.
