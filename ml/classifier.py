"""Production-facing category and severity classifier."""

from pathlib import Path
import re
import time
from typing import Any

import joblib
import numpy as np

from .subcategory_rules import high_confidence_category, predict_subcategory


DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "category_model.joblib"
MIN_WORDS = 3
MIN_CONFIDENCE = 0.55

_PRIORITY_BY_SEVERITY = {"Critical": "P1", "High": "P2", "Medium": "P3", "Low": "P4"}
CRITICAL_DEPARTMENTS = {"IT", "FINANCE"}
_PRIORITY_ESCALATION = {"P4": "P3", "P3": "P2", "P2": "P1", "P1": "P1"}


def load_artifact(model_path: str | Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    """Load the exported category vectorizer and classifier."""
    return joblib.load(model_path)


def classify_category(text: str, model_path: str | Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    """Classify a ticket into a category and subcategory."""
    text = str(text or "").strip()
    if not text or len(re.findall(r"\b\w+\b", text)) < MIN_WORDS:
        return {"category": "Unknown", "sub_category": "Other", "category_confidence": 0.0, "category_needs_review": True}

    rule_category = high_confidence_category(text)
    if rule_category is not None:
        return {"category": rule_category, "sub_category": predict_subcategory(text, rule_category), "category_confidence": 0.99}

    artifact = load_artifact(model_path)
    probabilities = artifact["model"].predict_proba(artifact["vectorizer"].transform([text]))[0]
    index = int(np.argmax(probabilities))
    category = str(artifact["model"].classes_[index])
    confidence = float(probabilities[index])
    result = {"category": category, "sub_category": predict_subcategory(text, category), "category_confidence": round(confidence, 4)}
    if confidence < MIN_CONFIDENCE:
        result["category_needs_review"] = True
    return result


_SEVERITY_RULES = (
    ("Critical", re.compile(r"\b(?:company[- ]wide|organisation[- ]wide|organization[- ]wide|all users|everyone|entire company|major security incident|critical security incident|confirmed data breach|ransomware|production (?:system )?(?:is )?down|complete(?:ly)? unavailable|critical business system|widespread outage|major data loss)\b", re.IGNORECASE), 0.92),
    ("High", re.compile(r"\b(?:multiple users|many users|entire team|whole team|all team members|service unavailable|major disruption|business operations|system outage|outage|cannot access important|down for (?:the )?team|multiple applications|several employees|multiple employees)\b", re.IGNORECASE), 0.86),
    ("Medium", re.compile(r"\b(?:individual user|one user|significant issue|workaround|unable to access|cannot access|can't access|blocked|intermittent|connection problems?|connection timeout|connection timed out|connectivity timed out|slow application|application is slow|slow performance|performance degradation|authentication failed|login failure)\b", re.IGNORECASE), 0.78),
    ("Low", re.compile(r"\b(?:minor inconvenience|cosmetic|non[- ]urgent|routine request|software installation|how do i|how can i|general question|requesting information|seeking guidance|install approved software|approved software installation|could you explain|change my email signature)\b", re.IGNORECASE), 0.82),
)


def _is_negated_match(text: str, match_start: int) -> bool:
    """Check whether an impact phrase is explicitly negated."""
    preceding = text[max(0, match_start - 60):match_start]
    following = text[match_start:match_start + 100]
    return bool(
        re.search(r"\b(?:not|no|never|without|isn't|is not|wasn't|was not|ruled out|no evidence of|not detected)(?:\s+\w+){0,5}\s*$", preceding, re.IGNORECASE)
        or re.search(r"^\s*(?:is\s+|was\s+|has\s+been\s+|were\s+|are\s+)?not\s+(?:affected|impacted|experiencing|experiencing any)", following, re.IGNORECASE)
    )


def classify_severity(text: str) -> tuple[str, float]:
    """Infer severity from impact and return a confidence score."""
    text = str(text or "").strip().lower()
    if not text:
        return "Unknown", 0.0
    if re.search(r"\bnot\s+(?:a\s+)?critical issue\b", text):
        return "Medium", 0.55

    uncertain_security = re.search(r"\b(?:potential|possible|suspected|alleged)\b.{0,100}\b(?:breach|ransomware|unauthori[sz]ed access|security incident|data exposure)\b|\b(?:may|might|could)\s+have\b.{0,80}\b(?:exposed|compromised|breached)\b", text, re.IGNORECASE)
    if uncertain_security:
        return "Unknown", 0.0

    routine_password_reset = re.search(r"\b(?:password reset|reset my password|forgot my password|password recovery|unlock my account|locked out of my account)\b", text, re.IGNORECASE)
    active_security_incident = re.search(r"\b(?:unauthori[sz]ed access|confirmed data breach|ransomware|active security incident|data exposure)\b", text, re.IGNORECASE)
    if routine_password_reset and not active_security_incident:
        return "Low", 0.82

    informational = re.search(r"\b(?:could you explain|how do i|how can i|general question|seeking guidance|requesting information|change my email signature|install approved software|routine request|minor inconvenience|cosmetic issue)\b", text, re.IGNORECASE)
    active_incident = re.search(r"\b(?:outage|system is down|production down|service unavailable|data breach|ransomware|unauthori[sz]ed access|security incident|data loss|cannot access|can't access|unable to access)\b", text, re.IGNORECASE)
    if informational and not active_incident:
        return "Low", 0.82

    limited_impact = re.search(r"\b(?:printer jam(?:med)?|printer is jammed|wi[- ]?fi is very slow|wi[- ]?fi is slow|slow wi[- ]?fi|slow network connection)\b", text, re.IGNORECASE)
    wider_impact = re.search(r"\b(?:all users|multiple users|many users|whole team|entire team|several employees|multiple employees|company[- ]wide|production (?:system )?(?:is )?down|widespread outage|service unavailable)\b", text, re.IGNORECASE)
    if limited_impact and not wider_impact:
        return "Medium", 0.75
    if re.search(r"\b(?:connection|connectivity)\s+timed?\s*out\b|\bconnection timeout\b", text, re.IGNORECASE) and not wider_impact:
        return "Medium", 0.75

    for severity, pattern, confidence in _SEVERITY_RULES:
        for match in pattern.finditer(text):
            if not _is_negated_match(text, match.start()):
                return severity, confidence
    return "Unknown", 0.0


def classify(subject: str | None, description: str, department: str | None = None) -> dict[str, Any]:
    """Return category, severity, priority, confidence, and processing time."""
    start_time = time.perf_counter()
    text = " ".join(part for part in (subject or "", description or "") if part).strip()
    result = classify_category(text)
    severity, severity_confidence = classify_severity(text)
    needs_human_review = severity == "Unknown" or result.get("category") == "Unknown" or result.get("category_needs_review", False)
    priority = "P3" if severity == "Unknown" else _PRIORITY_BY_SEVERITY[severity]
    department_name = str(department or "").strip().upper()
    if severity != "Unknown" and department_name in CRITICAL_DEPARTMENTS:
        priority = _PRIORITY_ESCALATION[priority]
    result.update({
        "severity": severity,
        "needs_human_review": needs_human_review,
        "severity_confidence": severity_confidence,
        "priority": priority,
        "processing_ms": round((time.perf_counter() - start_time) * 1000, 2),
    })
    return result
