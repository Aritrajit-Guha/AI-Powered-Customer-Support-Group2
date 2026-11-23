"""Role B orchestration: Diagnosis -> Retrieval -> Resolution -> Validation -> Escalation."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import os
from typing import Any

from .diagnosis import diagnose
from .escalation import decide
from .validation import validate


def _trace(
    agent: str,
    started: float | None,
    confidence: float | None,
    summary: str,
    status: str = "ok",
    output: dict[str, Any] | None = None,
    duration_ms: float | None = None,
) -> dict[str, Any]:
    return {
        "agent": agent,
        "status": status,
        "ms": round(duration_ms, 2) if duration_ms is not None else round((time.perf_counter() - started) * 1000, 2),
        "confidence": None if confidence is None else round(max(0.0, min(1.0, confidence)), 4),
        "summary": summary,
        "output": output or {},
    }


def _safe_resolution(ticket: dict[str, Any], diagnosis: dict[str, Any]) -> dict[str, Any]:
    """Use the real RAG pipeline first, then a safe no-credential response."""
    try:
        from rag.pipeline import resolve

        return resolve(ticket.get("subject", ""), ticket.get("description", ""), ticket.get("category", "Unknown"))
    except Exception as exc:
        return {
            "response_text": (
                "Hello,\n\nWe could not retrieve a sufficiently reliable knowledge-base article "
                "for this ticket. A support engineer will review it."
            ),
            "steps": [], "sources": [], "articles": [], "confidence": 0.0,
            "mode": "retrieval_error", "needs_human_review": True,
            "trace": [{"step": "retrieval_error", "error": type(exc).__name__}],
            "response_ms": 0.0,
        }


def _timed_resolution(ticket: dict[str, Any], diagnosis: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    """Bound retrieval/resolution latency and return a safe result on timeout."""
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_safe_resolution, ticket, diagnosis)
    try:
        return future.result(timeout=max(0.05, timeout_seconds))
    except TimeoutError:
        future.cancel()
        return {
            "response_text": (
                "Hello,\n\nThe automated knowledge-base lookup took too long to complete. "
                "A support engineer will review this ticket."
            ),
            "steps": [], "sources": [], "articles": [], "confidence": 0.0,
            "mode": "timeout", "needs_human_review": True, "trace": [], "response_ms": 0.0,
        }
    finally:
        # Do not make the request wait for a stuck network call after the deadline.
        executor.shutdown(wait=False, cancel_futures=True)


def run(ticket: dict[str, Any]) -> dict[str, Any]:
    """Run the complete workflow without writing to the database."""
    trace = []

    workflow_start = time.perf_counter()
    max_seconds = float(os.environ.get("AGENT_MAX_SECONDS", "4.8"))

    started = time.perf_counter()
    diagnosis = diagnose(ticket)
    trace.append(_trace(
        "Diagnosis", started, float(diagnosis.get("confidence", 0.0)), diagnosis.get("summary", ""),
        output=diagnosis,
    ))

    started = time.perf_counter()
    remaining = max(0.1, max_seconds - (time.perf_counter() - workflow_start))
    resolution = _timed_resolution(ticket, diagnosis, remaining)
    pipeline_trace = resolution.get("trace") or []
    stage_times = {
        str(item.get("step")): item.get("time_ms", item.get("ms"))
        for item in pipeline_trace if isinstance(item, dict)
    }
    retrieval_ms = stage_times.get("retrieve_articles")
    resolution_ms = stage_times.get("generate_response")
    if retrieval_ms is None and resolution_ms is None:
        # A fallback/error response has one measured resolution call, not two
        # falsely identical agent durations.
        retrieval_ms = round((time.perf_counter() - started) * 1000, 2)
        resolution_ms = 0.0
    trace.append(_trace(
        "Retrieval", None, float(resolution.get("confidence", 0.0)),
        f"Retrieved {len(resolution.get('articles') or [])} article(s).",
        duration_ms=float(retrieval_ms or 0.0),
        output={"articles": resolution.get("articles") or [], "sources": resolution.get("sources") or []},
    ))
    trace.append(_trace(
        "Resolution", None, float(resolution.get("confidence", 0.0)),
        f"Response mode: {resolution.get('mode', 'unknown')}",
        duration_ms=float(resolution_ms or 0.0),
        output={"response_text": resolution.get("response_text", ""), "steps": resolution.get("steps") or []},
    ))

    started = time.perf_counter()
    validation = validate(resolution)
    resolution["confidence"] = validation["confidence"]
    resolution["needs_human_review"] = bool(resolution.get("needs_human_review") or not validation["passed"])
    trace.append(_trace(
        "Validation", started, validation["confidence"], validation["notes"],
        "ok" if validation["passed"] else "review", output=validation,
    ))

    started = time.perf_counter()
    decision = decide(ticket, resolution, validation, diagnosis)
    trace.append(_trace("Escalation", started, validation["confidence"], decision["reason"] or "Auto-resolution allowed."))

    return {
        "agent_trace": trace,
        "diagnosis": diagnosis,
        "resolution": resolution,
        "validation": validation,
        **decision,
    }
