# Milestone 3 Role B: multi-agent AI

The `agents/` package implements a database-independent workflow:

1. `Diagnosis` creates a structured summary, suspected cause, missing information, urgency, and confidence. Gemini is available when `AGENT_DIAGNOSIS_MODE=gemini`; deterministic rules are the default fallback.
2. `Retrieval` and `Resolution` reuse `rag.pipeline.resolve`, which retrieves knowledge-base articles and creates an article-grounded response. If vector retrieval is unavailable, the orchestrator returns a safe human-review response.
3. `Validation` checks that every returned troubleshooting step is supported by retrieved article content and lowers confidence when grounding is weak.
4. `Escalation` decides between `auto_resolve` and `escalate`. Unknown, Security, Critical, low-confidence, and ungrounded cases escalate with a suggested team and reason.

The orchestrator returns `agent_trace`, `diagnosis`, `resolution`, `validation`, `decision`, `escalate_to`, and `reason`. It does not write to the database. Role A stores each trace item in `agent_runs` and stores the response in `ticket_responses`.

Optional extras are exposed by `agents.duplicate` and `agents.recurring`. Duplicate detection uses the separate `PINECONE_TICKET_NAMESPACE`. The recurring detector can be scheduled with `python -m agents.recurring`; it upserts repeated issue signatures into `recurring_issues`.

Performance summaries are available through `agents.metrics.summarize` and report run count, average duration, success rate, and average confidence per agent.
