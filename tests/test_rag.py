import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rag import config, index_kb, retriever
from rag.article_store import iter_articles, parse_article
from rag.eval_retrieval import evaluate


ARTICLE = """---
title: VPN connection timed out
category: VPN
keywords: vpn, timeout
---
Symptoms: VPN timeout.

Steps:
1. Check internet access.
2. Restart the client.
3. Verify the profile.
4. Retry.
5. Record the error.

Escalate if: the issue continues.
"""


class FakeIndex:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.queries = []
        self.upserts = []

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def delete(self, **kwargs):
        self.deleted = kwargs

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return self.responses.pop(0) if self.responses else {"matches": []}


class TestRag(unittest.TestCase):
    def test_article_validation_and_duplicate_slugs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "vpn-timeout.md"
            path.write_text(ARTICLE, encoding="utf-8")
            self.assertEqual(parse_article(path)["slug"], "vpn-timeout")
            self.assertEqual(len(iter_articles(root)), 1)
            duplicate = root / "other"
            duplicate.mkdir()
            (duplicate / "vpn-timeout.md").write_text(ARTICLE, encoding="utf-8")
            with self.assertRaises(ValueError):
                iter_articles(root)

    @patch("rag.index_kb.get_index")
    @patch("rag.index_kb.embed_texts")
    @patch("rag.index_kb.iter_articles")
    def test_index_contract(self, mocked_articles, mocked_embed, mocked_index):
        article = parse_article(Path(tempfile.gettempdir()) / "missing.md") if False else {
            "slug": "vpn-timeout", "title": "VPN timeout", "category": "VPN",
            "keywords": "vpn", "content": "Steps:\n1. Retry.\n\nEscalate if: it continues.",
        }
        index = FakeIndex()
        mocked_articles.return_value = [article]
        mocked_embed.return_value = [[0.0] * config.EMBEDDING_DIMENSION]
        mocked_index.return_value = index
        self.assertEqual(index_kb.index_kb(), 1)
        self.assertEqual(index.upserts[0]["vectors"][0]["id"], "vpn-timeout")
        self.assertEqual(mocked_embed.call_args.args[1], "RETRIEVAL_DOCUMENT")

    @patch("rag.retriever.get_index")
    @patch("rag.retriever.embed_text")
    def test_category_fallback(self, mocked_embed, mocked_index):
        index = FakeIndex([
            {"matches": []},
            {"matches": [{"id": "vpn-timeout", "score": 0.9, "metadata": {
                "slug": "vpn-timeout", "title": "VPN timeout", "category": "VPN", "content": "Steps"
            }}]},
        ])
        mocked_embed.return_value = [0.0] * config.EMBEDDING_DIMENSION
        mocked_index.return_value = index
        result = retriever.search_kb("VPN timeout", category="Software")
        self.assertEqual(result[0]["slug"], "vpn-timeout")
        self.assertNotIn("filter", index.queries[1])

    @patch("rag.retriever.get_index")
    @patch("rag.retriever.embed_text")
    def test_negative_cosine_scores_are_filtered(self, mocked_embed, mocked_index):
        index = FakeIndex([{"matches": [{"id": "bad", "score": -0.2, "metadata": {}}]}])
        mocked_embed.return_value = [0.0] * config.EMBEDDING_DIMENSION
        mocked_index.return_value = index
        self.assertEqual(retriever.search_kb("unrelated"), [])

    @patch("rag.index_kb.time.sleep")
    @patch("rag.index_kb.get_index")
    @patch("rag.index_kb.embed_texts", side_effect=RuntimeError("quota"))
    @patch("rag.index_kb.iter_articles")
    def test_failed_batch_is_logged_and_does_not_abort(self, mocked_articles, mocked_embed, mocked_index, mocked_sleep):
        articles = [{"slug": "failed", "title": "x", "category": "VPN", "keywords": "vpn", "content": "x"}]
        mocked_articles.return_value = articles
        mocked_index.return_value = FakeIndex()
        with tempfile.TemporaryDirectory() as folder:
            failure_path = Path(folder) / "failures.jsonl"
            with patch.object(config, "INDEX_FAILURES_PATH", failure_path):
                self.assertEqual(index_kb.index_kb(), 0)
            record = json.loads(failure_path.read_text(encoding="utf-8"))
            self.assertEqual(record["slugs"], ["failed"])

    @patch("rag.eval_retrieval.search_kb")
    def test_evaluation_metrics(self, mocked_search):
        with tempfile.TemporaryDirectory() as folder:
            test_file = Path(folder) / "set.csv"
            metrics_file = Path(folder) / "metrics.json"
            with test_file.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["ticket_text", "expected_category", "expected_slug", "source"])
                writer.writeheader()
                writer.writerow({"ticket_text": "vpn", "expected_category": "VPN", "expected_slug": "vpn-timeout", "source": "test"})
            mocked_search.return_value = [{"slug": "vpn-timeout"}]
            with patch.object(config, "METRICS_PATH", metrics_file):
                result = evaluate(test_file)
            self.assertEqual(result["hit_at_1"], 1.0)
            self.assertEqual(result["hit_at_3"], 1.0)


if __name__ == "__main__":
    unittest.main()
