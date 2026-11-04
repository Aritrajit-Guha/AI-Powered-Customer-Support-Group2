"""Configuration shared by the indexing and retrieval modules."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
KB_DIR = REPO_ROOT / "data" / "kb"
METRICS_PATH = REPO_ROOT / "data" / "retrieval_metrics.json"
INDEX_FAILURES_PATH = REPO_ROOT / "data" / "index_failures.jsonl"

load_dotenv(REPO_ROOT / ".env")

MIN_RELEVANCE = float(os.getenv("MIN_RELEVANCE", "0.35"))
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.60"))

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSION = 768
EMBEDDING_MAX_CHARS = 7000
EMBEDDING_BATCH_SIZE = 8
MAX_RETRIES = int(os.getenv("RAG_MAX_RETRIES", "4"))
RETRY_BASE_SECONDS = float(os.getenv("RAG_RETRY_BASE_SECONDS", "0.5"))
INDEX_BATCH_DELAY_SECONDS = float(os.getenv("RAG_INDEX_BATCH_DELAY_SECONDS", "8"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "customer-support-kb")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "customer-support-kb")
PINECONE_CLOUD = os.getenv("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.getenv("PINECONE_REGION", "us-east-1")
