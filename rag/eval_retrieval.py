"""Evaluate retrieval against data/kb_test_set.csv."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import time

from . import config
from .retriever import search_kb


def evaluate(test_path: Path | None = None) -> dict:
    test_path = Path(test_path or config.REPO_ROOT / "data" / "kb_test_set.csv")
    with test_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    failures = []
    hit1 = hit3 = 0
    latencies = []
    for row in rows:
        started = time.perf_counter()
        results = search_kb(row["ticket_text"], row.get("expected_category") or None, 3)
        latencies.append((time.perf_counter() - started) * 1000)
        slugs = [item["slug"] for item in results]
        expected = row["expected_slug"]
        if slugs[:1] == [expected]:
            hit1 += 1
        if expected in slugs[:3]:
            hit3 += 1
        else:
            failures.append({"ticket_text": row["ticket_text"], "expected_slug": expected, "returned_slugs": slugs})
    total = len(rows)
    metrics = {
        "count": total,
        "hit_at_1": hit1 / total if total else 0.0,
        "hit_at_3": hit3 / total if total else 0.0,
        "average_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
        "failures": failures,
    }
    config.METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


if __name__ == "__main__":
    result = evaluate()
    print(json.dumps({k: v for k, v in result.items() if k != "failures"}, indent=2))
    for failure in result["failures"]:
        print(f"FAIL: {failure['expected_slug']} <- {failure['returned_slugs']}")
