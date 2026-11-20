
"""Knowledge-base resolution generation pipeline for customer support tickets."""

from __future__ import annotations

import re
import time

from . import config
from .retriever import search_kb


def _clean_query(subject: str, description: str, category: str) -> str:
    """Remove greetings and signatures before building the retrieval query."""
    text = f"{subject or ''}\n{description or ''}".strip()

    text = re.sub(
        r"(?im)^\s*(hi|hello|dear team|dear support|good morning|good afternoon)[,!.\s]*",
        "",
        text,
    )
    text = re.split(
        r"(?im)^\s*(thanks|thank you|regards|best regards|sincerely)[,!.\s]*$",
        text,
        maxsplit=1,
    )[0]

    text = re.sub(r"\s+", " ", text).strip()

    if category and category.lower() != "unknown":
        text = f"{category}: {text}"

    return text


def _extract_steps(content: str) -> list[str]:
    """Extract numbered steps from an article."""
    match = re.search(
        r"(?ims)^Steps:\s*(.*?)(?=^\s*(?:Escalate if:|Safety note:)|\Z)",
        content or "",
    )
    if not match:
        return []

    steps = []
    for line in match.group(1).splitlines():
        item = re.match(r"^\s*\d+[.)]\s+(.+?)\s*$", line)
        if item:
            steps.append(item.group(1).strip())

    return steps


def _extract_section(content: str, heading: str) -> str:
    """Extract a single-line article instruction."""
    match = re.search(
        rf"(?im)^\s*{re.escape(heading)}\s*:\s*(.+?)\s*$",
        content or "",
    )
    return match.group(1).strip() if match else ""


def _confidence(articles: list[dict], category: str) -> float:
    """Calculate confidence using relevance, category match and score gap."""
    if not articles:
        return 0.0

    top_score = float(articles[0].get("score", 0.0))
    second_score = (
        float(articles[1].get("score", 0.0))
        if len(articles) > 1
        else 0.0
    )

    category_match = (
        1.0
        if category
        and category.lower() != "unknown"
        and articles[0].get("category", "").lower() == category.lower()
        else 0.0
    )

    score_gap = max(0.0, top_score - second_score)

    confidence = (
        0.50 * max(0.0, min(1.0, top_score))
        + 0.30 * category_match
        + 0.20 * max(0.0, min(1.0, score_gap))
    )

    return round(confidence, 4)


def _default_response(article: dict, steps: list[str]) -> str:
    """Build a response using only retrieved article information."""
    title = article.get("title") or "the knowledge-base article"
    escalation = _extract_section(article.get("content", ""), "Escalate if")
    safety = _extract_section(article.get("content", ""), "Safety note")

    lines = [
        "Hello,",
        "",
        f"Based on the article '{title}', please follow these steps:",
    ]

    for number, step in enumerate(steps, start=1):
        lines.append(f"{number}. {step}")

    if escalation:
        lines.extend(["", f"Escalate if: {escalation}"])

    if safety:
        lines.extend(["", f"Safety note: {safety}"])

    lines.extend(["", "Sources:", f"- {title}"])

    return "\n".join(lines)


def _review_response() -> str:
    return (
        "Hello,\n\n"
        "I could not find a sufficiently reliable knowledge-base solution "
        "for this ticket. A support engineer will review the issue and "
        "provide the appropriate next steps.\n\n"
        "Please do not attempt unverified troubleshooting steps."
    )


def resolve(subject: str, description: str, category: str) -> dict:
    """Retrieve relevant articles and generate a safe support response."""
    start = time.perf_counter()
    trace = []

    def record_step(name: str, step_start: float) -> None:
        trace.append({
            "step": name,
            "time_ms": round((time.perf_counter() - step_start) * 1000, 2),
        })

    # Step 1: Analyze the ticket and build a retrieval query.
    step_start = time.perf_counter()
    query = _clean_query(subject, description, category)
    record_step("analyze_ticket", step_start)

    # Step 2: Retrieve relevant knowledge-base articles.
    step_start = time.perf_counter()
    articles = search_kb(query, category=category, top_k=3)
    record_step("retrieve_articles", step_start)

    confidence = _confidence(articles, category)

    valid_articles = [
        article for article in articles
        if float(article.get("score", 0.0)) >= config.MIN_RELEVANCE
    ]

    best_article = valid_articles[0] if valid_articles else None
    steps = _extract_steps(best_article.get("content", "")) if best_article else []

    needs_review = (
        not best_article
        or not steps
        or confidence < config.CONFIDENCE_THRESHOLD
        or not category
        or category.lower() == "unknown"
    )

    # Step 3: Add retrieved article context.
    step_start = time.perf_counter()
    context = best_article.get("content", "") if best_article else ""
    record_step("add_context", step_start)

    # Step 4: Generate a response from the retrieved context.
    step_start = time.perf_counter()
    if needs_review:
        response_text = _review_response()
        mode = "human_review"
        steps = []
        sources = []
    else:
        response_text = _default_response(best_article, steps)
        mode = "default"
        sources = [best_article.get("title", "")]

    record_step("generate_response", step_start)

    response_ms = round((time.perf_counter() - start) * 1000, 2)

    return {
        "response_text": response_text,
        "steps": steps,
        "sources": sources,
        "articles": articles,
        "confidence": confidence,
        "mode": mode,
        "needs_human_review": needs_review,
        "trace": trace,
        "response_ms": response_ms,
    }
