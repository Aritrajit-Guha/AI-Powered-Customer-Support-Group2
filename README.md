# AI-Powered Customer Support Platform

An AI-powered platform for analyzing and managing customer support tickets.

## Project Structure

- `backend/` — Backend APIs and business logic.
- `ml/` — Machine learning models and classification pipelines.
- `data/` — Project datasets.
- `docs/` — Project documentation.
- `frontend/` — User interface.
- `rag/` — Gemini embeddings, Pinecone indexing, retrieval, and evaluation.

## Knowledge base and retrieval

The starter knowledge base is under `data/kb/`. It contains reviewed Markdown
articles with title, category, keywords, troubleshooting steps, and escalation
guidance. Pinecone must have a 768-dimensional cosine index before indexing.

Set these environment variables locally:

```text
GEMINI_API_KEY=...
PINECONE_API_KEY=...
PINECONE_INDEX_NAME=customer-support-kb
PINECONE_NAMESPACE=customer-support-kb
```

From the repository root:

```text
python -m rag.index_kb
python -m rag.eval_retrieval
```

For a replacement corpus, regenerate from the PDF and rebuild Pinecone:

```text
python -m rag.import_pdf
python -m rag.index_kb --rebuild
```

If Gemini quota interrupts indexing, resume with the last successful article
offset, for example `python -m rag.index_kb --start 248`.

The retrieval evaluation reads `data/kb_test_set.csv` when Person E provides
the shared test set and writes `data/retrieval_metrics.json`.

## Team Workflow

We use GitHub branches and pull requests to collaborate.
