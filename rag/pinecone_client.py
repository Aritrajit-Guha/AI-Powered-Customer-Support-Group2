"""Lazy Pinecone client access used by the indexer and retriever."""

from functools import lru_cache

from pinecone import Pinecone

from . import config


@lru_cache(maxsize=1)
def get_index():
    if not config.PINECONE_API_KEY:
        raise RuntimeError("PINECONE_API_KEY is required for vector retrieval")
    if not config.PINECONE_INDEX_NAME:
        raise RuntimeError("PINECONE_INDEX_NAME is required for vector retrieval")
    return Pinecone(api_key=config.PINECONE_API_KEY).Index(config.PINECONE_INDEX_NAME)
