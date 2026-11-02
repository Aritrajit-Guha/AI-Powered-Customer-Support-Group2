"""Index Markdown knowledge-base articles in Pinecone."""

from __future__ import annotations

import argparse
import time

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
    count = 0
    for start in range(0, len(articles), config.EMBEDDING_BATCH_SIZE):
        batch = articles[start:start + config.EMBEDDING_BATCH_SIZE]
        vectors = embed_texts([_embedding_text(item) for item in batch], RETRIEVAL_DOCUMENT)
        payload = []
        for article, vector in zip(batch, vectors):
            payload.append(
                {
                    "id": article["slug"],
                    "values": vector,
                    "metadata": {
                        "slug": article["slug"],
                        "title": article["title"],
                        "category": article["category"],
                        "keywords": article["keywords"],
                        "content": article["content"],
                    },
                }
            )
        index.upsert(vectors=payload, namespace=config.PINECONE_NAMESPACE)
        count += len(payload)
        print(f"Indexed {count}/{len(articles)} articles")
        if count < len(articles) and config.INDEX_BATCH_DELAY_SECONDS > 0:
            time.sleep(config.INDEX_BATCH_DELAY_SECONDS)
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="clear the namespace before indexing")
    parser.add_argument("--start", type=int, default=0, help="zero-based article offset for resuming")
    args = parser.parse_args()
    print(f"Indexed articles: {index_kb(clear_existing=args.rebuild, start=args.start)}")
