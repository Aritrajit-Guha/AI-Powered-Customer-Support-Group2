"""Pure helpers for agent performance reporting."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def summarize(runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[str(run.get("agent") or run.get("agent_name") or "unknown")].append(run)
    output = {}
    for name, items in grouped.items():
        durations = [float(x["ms"] if "ms" in x else x.get("duration_ms", 0.0) or 0.0) for x in items]
        confidences = [float(x["confidence"]) for x in items if x.get("confidence") is not None]
        successes = sum(1 for x in items if str(x.get("status", "ok")).lower() in {"ok", "success"})
        output[name] = {
            "runs": len(items),
            "average_time_ms": round(sum(durations) / len(durations), 2) if durations else 0.0,
            "success_rate": round(successes / len(items), 4) if items else 0.0,
            "average_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
        }
    return output
