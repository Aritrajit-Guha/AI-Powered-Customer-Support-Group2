"""Lazy Pinecone client access used by the indexer and retriever."""

from functools import lru_cache

from pinecone import Pinecone, ServerlessSpec

from . import config


@lru_cache(maxsize=1)
def get_index():
    if not config.PINECONE_API_KEY:
        raise RuntimeError("PINECONE_API_KEY is required for vector retrieval")
    if not config.PINECONE_INDEX_NAME:
        raise RuntimeError("PINECONE_INDEX_NAME is required for vector retrieval")
    client = Pinecone(api_key=config.PINECONE_API_KEY)
    if config.PINECONE_INDEX_NAME not in set(client.list_indexes().names()):
        client.create_index(
            name=config.PINECONE_INDEX_NAME,
            dimension=config.EMBEDDING_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud=config.PINECONE_CLOUD, region=config.PINECONE_REGION),
        )
    return client.Index(config.PINECONE_INDEX_NAME)
