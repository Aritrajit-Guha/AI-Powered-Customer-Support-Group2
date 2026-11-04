"""Gemini embedding adapter with caching, normalization, and bounded retries."""

from __future__ import annotations

from functools import lru_cache
import time
from typing import Iterable

from langchain_google_genai import GoogleGenerativeAIEmbeddings
import numpy as np

from . import config


RETRIEVAL_DOCUMENT = "RETRIEVAL_DOCUMENT"
RETRIEVAL_QUERY = "RETRIEVAL_QUERY"


@lru_cache(maxsize=2)
def get_embeddings(task_type: str) -> GoogleGenerativeAIEmbeddings:
    """Create one LangChain embedding adapter per retrieval task type."""
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is required for retrieval embeddings")
    return GoogleGenerativeAIEmbeddings(
        model=config.EMBEDDING_MODEL,
        api_key=config.GEMINI_API_KEY,
        task_type=task_type,
    )


def _bounded_text(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text[: config.EMBEDDING_MAX_CHARS]


def _normalize(values: Iterable[float]) -> list[float]:
    vector = np.asarray(list(values), dtype=np.float32)
    if vector.size != config.EMBEDDING_DIMENSION:
        raise ValueError(
            f"Expected {config.EMBEDDING_DIMENSION}-dimensional embedding, "
            f"received {vector.size}"
        )
    norm = float(np.linalg.norm(vector))
    if not norm:
        raise ValueError("Embedding response contained a zero vector")
    return (vector / norm).tolist()


def embed_texts(texts: list[str], task_type: str) -> list[list[float]]:
    """Embed texts with bounded exponential backoff."""
    if not texts:
        return []
    contents = [_bounded_text(text) for text in texts]
    last_error = None
    for attempt in range(config.MAX_RETRIES):
        try:
            vectors = get_embeddings(task_type).embed_documents(
                contents,
                batch_size=len(contents),
                task_type=task_type,
                output_dimensionality=config.EMBEDDING_DIMENSION,
            )
            if len(vectors) != len(contents):
                raise ValueError("Gemini returned an unexpected number of embeddings")
            return [_normalize(vector) for vector in vectors]
        except ValueError:
            raise
        except Exception as exc:  # SDK exceptions vary across versions.
            last_error = exc
            if attempt + 1 == config.MAX_RETRIES:
                break
            time.sleep(config.RETRY_BASE_SECONDS * (2**attempt))
    raise RuntimeError("Gemini embedding request failed") from last_error


def embed_text(text: str, task_type: str) -> list[float]:
    """Embed one text using the same path as batch indexing."""
    return embed_texts([text], task_type)[0]
