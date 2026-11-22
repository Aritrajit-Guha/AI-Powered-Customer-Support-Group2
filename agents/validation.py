"""Grounding checks for generated troubleshooting steps."""

from __future__ import annotations

import re
from typing import Any


def _tokens(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(x) > 2}


def validate(resolution: dict[str, Any]) -> dict[str, Any]:
    steps = list(resolution.get("steps") or [])
    articles = list(resolution.get("articles") or [])
    content = "\n".join(str(a.get("content") or "") for a in articles if isinstance(a, dict))
    content_tokens = _tokens(content)
    unsupported = []
    for step in steps:
        step_tokens = _tokens(str(step))
        overlap = len(step_tokens & content_tokens) / max(1, len(step_tokens))
        if overlap < 0.55:
            unsupported.append(str(step))

    base = max(0.0, min(1.0, float(resolution.get("confidence", 0.0))))
    passed = bool(steps) and not unsupported and bool(articles)
    confidence = round(base if passed else base * 0.5, 4)
    notes = "All response steps are supported by retrieved article content." if passed else (
        "Response contains no usable steps." if not steps else
        f"Unsupported or weakly grounded step(s): {len(unsupported)}."
    )
    return {"passed": passed, "confidence": confidence, "notes": notes, "unsupported_steps": unsupported}
