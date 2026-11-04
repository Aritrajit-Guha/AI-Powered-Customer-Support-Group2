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
    description = client.describe_index(config.PINECONE_INDEX_NAME)
    dimension = getattr(description, "dimension", None)
    metric = getattr(description, "metric", None)
    if isinstance(description, dict):
        dimension = description.get("dimension", dimension)
        metric = description.get("metric", metric)
    if int(dimension) != config.EMBEDDING_DIMENSION or str(metric).lower() != "cosine":
        raise RuntimeError(
            f"Pinecone index {config.PINECONE_INDEX_NAME!r} has dimension={dimension} "
            f"and metric={metric!r}; expected dimension={config.EMBEDDING_DIMENSION} and metric='cosine'"
        )
    return client.Index(config.PINECONE_INDEX_NAME)
