"""Index Markdown knowledge-base articles in Pinecone."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from . import config
from .article_store import iter_articles
from .embeddings import RETRIEVAL_DOCUMENT, embed_texts
from .pinecone_client import get_index


def _embedding_text(article: dict[str, str]) -> str:
    return "\n".join(
        (
            f"Title: {article['title']}",
            f"Category: {article['category']}",
            f"Keywords: {article['keywords']}",
            article["content"],
        )
    )


def _log_failure(batch_number: int, articles: list[dict[str, str]], error: Exception) -> None:
    config.INDEX_FAILURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "batch": batch_number,
        "slugs": [article["slug"] for article in articles],
        "error": f"{type(error).__name__}: {error}",
    }
    with config.INDEX_FAILURES_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")
    print(f"Failed batch {batch_number}; logged {len(articles)} article(s)")


def _index_batch(index, batch: list[dict[str, str]]) -> int:
    """Embed and upsert one batch with bounded retries for transient failures."""
    last_error = None
    for attempt in range(config.MAX_RETRIES):
        try:
            vectors = embed_texts([_embedding_text(item) for item in batch], RETRIEVAL_DOCUMENT)
            payload = [
                {
                    "id": article["slug"],
                    "values": vector,
                    "metadata": {
                        "slug": article["slug"], "title": article["title"],
                        "category": article["category"], "keywords": article["keywords"],
                        "content": article["content"],
                    },
                }
                for article, vector in zip(batch, vectors)
            ]
            index.upsert(vectors=payload, namespace=config.PINECONE_NAMESPACE)
            return len(payload)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < config.MAX_RETRIES:
                time.sleep(config.RETRY_BASE_SECONDS * (2**attempt))
    raise RuntimeError("Embedding or Pinecone upsert failed after retries") from last_error


def index_kb(clear_existing: bool = False, start: int = 0) -> int:
    """Upsert Markdown articles and return the number processed.

    ``start`` allows a rate-limited run to resume without clearing completed
    vectors. Use ``clear_existing=True`` for a deliberate full rebuild.
    """
    articles = iter_articles(config.KB_DIR)
    if start < 0 or start > len(articles):
        raise ValueError(f"start must be between 0 and {len(articles)}")
    articles = articles[start:]
    if not articles:
        return 0
    index = get_index()
    if clear_existing:
        index.delete(delete_all=True, namespace=config.PINECONE_NAMESPACE)
        if config.INDEX_FAILURES_PATH.exists():
            config.INDEX_FAILURES_PATH.unlink()
    count = 0
    for offset in range(0, len(articles), config.EMBEDDING_BATCH_SIZE):
        batch = articles[offset:offset + config.EMBEDDING_BATCH_SIZE]
        try:
            count += _index_batch(index, batch)
            print(f"Indexed {count}/{len(articles)} articles")
        except Exception as exc:
            _log_failure(offset // config.EMBEDDING_BATCH_SIZE, batch, exc)
        if count < len(articles) and config.INDEX_BATCH_DELAY_SECONDS > 0:
            time.sleep(config.INDEX_BATCH_DELAY_SECONDS)
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="clear the namespace before indexing")
    parser.add_argument("--start", type=int, default=0, help="zero-based article offset for resuming")
    args = parser.parse_args()
    print(f"Indexed articles: {index_kb(clear_existing=args.rebuild, start=args.start)}")
