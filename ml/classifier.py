# """Production-facing category classifier for Person 3 and the backend."""

# from pathlib import Path
# from typing import Any

# import joblib
# import numpy as np
# import re

# from .subcategory_rules import high_confidence_category, predict_subcategory


# DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "category_model.joblib"
# MIN_WORDS = 3
# MIN_CONFIDENCE = 0.55


# def load_artifact(model_path: str | Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
#     """Load the exported vectorizer and classifier artifact."""
#     return joblib.load(model_path)


# def classify_category(text: str, model_path: str | Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
#     """Classify one ticket and return the agreed integration contract."""
#     text = str(text).strip()
#     if not text or len(re.findall(r"\b\w+\b", text)) < MIN_WORDS:
#         return {
#             "category": "Unknown",
#             "sub_category": "Other",
#             "category_confidence": 0.0,
#         }

#     rule_category = high_confidence_category(text)
#     if rule_category is not None:
#         return {
#             "category": rule_category,
#             "sub_category": predict_subcategory(text, rule_category),
#             "category_confidence": 0.99,
#         }

#     artifact = load_artifact(model_path)
#     vectorizer = artifact["vectorizer"]
#     model = artifact["model"]
#     features = vectorizer.transform([text])
#     probabilities = model.predict_proba(features)[0]
#     index = int(np.argmax(probabilities))
#     category = str(model.classes_[index])
#     confidence = float(probabilities[index])
#     if confidence < MIN_CONFIDENCE:
#         return {
#             "category": "Unknown",
#             "sub_category": "Other",
#             "category_confidence": round(confidence, 4),
#         }
#     return {
#         "category": category,
#         "sub_category": predict_subcategory(text, category),
#         "category_confidence": round(confidence, 4),
#     }


# # Explicit severity words are the strongest signal.  If a requester does not
# # provide one, the transparent rules below infer severity from the impact
# # described in the ticket.
# _EXPLICIT_SEVERITIES = ("Critical", "High", "Medium", "Low")
# _SEVERITY_RULES = (
#     (
#         "Critical",
#         re.compile(
#             r"company[- ]wide|organisation[- ]wide|organization[- ]wide|"
#             r"all users|everyone|entire company|major security incident|"
#             r"ransomware|data breach|production (?:is )?down|complete(?:ly)? unavailable|"
#             r"critical business system"
#         ),
#         0.92,
#     ),
#     (
#         "High",
#         re.compile(
#             r"multiple users|many users|service unavailable|major disruption|"
#             r"business operations|system outage|outage|cannot access important|"
#             r"down for (?:the )?team"
#         ),
#         0.86,
#     ),
#     (
#         "Medium",
#         re.compile(
#             r"individual user|significant issue|workaround|unable to access|"
#             r"cannot access|can't access|blocked|intermittent"
#         ),
#         0.78,
#     ),
#     (
#         "Low",
#         re.compile(
#             r"minor inconvenience|cosmetic|non[- ]urgent|routine request|"
#             r"software installation|how do i|general question"
#         ),
#         0.82,
#     ),
# )
# _PRIORITY_BY_SEVERITY = {"Critical": "P1", "High": "P2", "Medium": "P3", "Low": "P4"}


# def classify_severity(text: str) -> tuple[str, float]:
#     """Return severity and confidence using explicit words, then impact rules."""
#     text = str(text).strip().lower()

#     for severity in _EXPLICIT_SEVERITIES:
#         if re.search(rf"\b{severity.lower()}\b", text):
#             return severity, 0.99

#     for severity, pattern, confidence in _SEVERITY_RULES:
#         if pattern.search(text):
#             return severity, confidence

#     # With no explicit impact signal, Medium is the safest neutral default.
#     return "Medium", 0.55


# def classify(subject: str | None, description: str, department: str | None = None) -> dict[str, Any]:
#     """Backend integration contract used by Person 3 and the API."""
#     text = " ".join(part for part in (subject or "", description or "") if part).strip()
#     result = classify_category(text)

#     severity, severity_confidence = classify_severity(text)
#     result.update(
#         {
#             "severity": severity,
#             "severity_confidence": severity_confidence,
#             "priority": _PRIORITY_BY_SEVERITY[severity],
#         }
#     )
#     return result

# """Production-facing category and severity classifier."""

# from pathlib import Path
# from typing import Any
# import re

# import joblib
# import numpy as np

# from .subcategory_rules import high_confidence_category, predict_subcategory


# DEFAULT_MODEL_PATH = (
#     Path(__file__).resolve().parent / "models" / "category_model.joblib"
# )
# MIN_WORDS = 3
# MIN_CONFIDENCE = 0.55


# def load_artifact(
#     model_path: str | Path = DEFAULT_MODEL_PATH,
# ) -> dict[str, Any]:
#     """Load the exported vectorizer and classifier artifact."""
#     return joblib.load(model_path)


# def classify_category(
#     text: str,
#     model_path: str | Path = DEFAULT_MODEL_PATH,
# ) -> dict[str, Any]:
#     """Classify one ticket and return the agreed integration contract."""
#     text = str(text or "").strip()

#     if not text or len(re.findall(r"\b\w+\b", text)) < MIN_WORDS:
#         return {
#             "category": "Unknown",
#             "sub_category": "Other",
#             "category_confidence": 0.0,
#         }

#     rule_category = high_confidence_category(text)

#     if rule_category is not None:
#         return {
#             "category": rule_category,
#             "sub_category": predict_subcategory(text, rule_category),
#             "category_confidence": 0.99,
#         }

#     artifact = load_artifact(model_path)
#     vectorizer = artifact["vectorizer"]
#     model = artifact["model"]

#     features = vectorizer.transform([text])
#     probabilities = model.predict_proba(features)[0]

#     index = int(np.argmax(probabilities))
#     category = str(model.classes_[index])
#     confidence = float(probabilities[index])

#     if confidence < MIN_CONFIDENCE:
#         return {
#             "category": "Unknown",
#             "sub_category": "Other",
#             "category_confidence": round(confidence, 4),
#         }

#     return {
#         "category": category,
#         "sub_category": predict_subcategory(text, category),
#         "category_confidence": round(confidence, 4),
#     }


# # Severity rules are ordered from highest to lowest impact.
# # Severity words alone are not automatically treated as ground truth.
# _SEVERITY_RULES = (
#     (
#         "Critical",
#         re.compile(
#             r"\b(?:"
#             r"company[- ]wide|organisation[- ]wide|organization[- ]wide|"
#             r"all users|everyone|entire company|"
#             r"major security incident|critical security incident|"
#             r"confirmed data breach|"
#             r"ransomware|production (?:is )?down|"
#             r"complete(?:ly)? unavailable|"
#             r"critical business system|"
#             r"widespread outage|major data loss"
#             r")\b",
#             re.IGNORECASE,
#         ),
#         0.92,
#     ),
#     (
#         "High",
#         re.compile(
#             r"\b(?:"
#             r"multiple users|many users|entire team|whole team|"
#             r"all team members|service unavailable|"
#             r"major disruption|business operations|"
#             r"system outage|outage|"
#             r"cannot access important|"
#             r"down for (?:the )?team|"
#             r"multiple applications"
#             r")\b",
#             re.IGNORECASE,
#         ),
#         0.86,
#     ),
#     (
#         "Medium",
#         re.compile(
#             r"\b(?:"
#             r"individual user|significant issue|workaround|"
#             r"unable to access|cannot access|can't access|"
#             r"blocked|intermittent|connection problems?|"
#             r"slow application|application is slow|"
#             r"slow performance|performance degradation|"
#             r"authentication failed|login failure"
#             r")\b",
#             re.IGNORECASE,
#         ),
#         0.78,
#     ),
#     (
#         "Low",
#         re.compile(
#             r"\b(?:"
#             r"minor inconvenience|cosmetic|non[- ]urgent|"
#             r"routine request|software installation|"
#             r"how do i|general question|"
#             r"requesting information|seeking guidance|"
#             r"install approved software|approved software installation"
#             r")\b",
#             re.IGNORECASE,
#         ),
#         0.82,
#     ),
# )

# _PRIORITY_BY_SEVERITY = {
#     "Critical": "P1",
#     "High": "P2",
#     "Medium": "P3",
#     "Low": "P4",
# }



# def _is_negated_match(text: str, match_start: int) -> bool:
#     """Check for negation immediately before or after an impact phrase."""
#     preceding_text = text[max(0, match_start - 60):match_start]
#     following_text = text[match_start:match_start + 100]

#     preceding_negation = re.compile(
#         r"\b(?:not|no|never|without|isn't|is not|"
#         r"wasn't|was not|ruled out|no evidence of|not detected)"
#         r"(?:\s+\w+){0,5}\s*$",
#         re.IGNORECASE,
#     )

#     # Handles: "not affected by the outage"
#     following_negation = re.compile(
#         r"^\s*(?:is\s+|was\s+|has\s+been\s+|were\s+|are\s+)?"
#         r"not\s+(?:affected|impacted|experiencing|experiencing any)",
#         re.IGNORECASE,
#     )

#     return bool(
#         preceding_negation.search(preceding_text)
#         or following_negation.search(following_text)
#     )





# def classify_severity(text: str) -> tuple[str, float]:
#     """Infer severity from ticket impact using ordered rules."""
#     text = str(text or "").strip().lower()

#     if not text:
#         return "Unknown", 0.0

#     # Check whether the team is explicitly described as unaffected.
#     team_unaffected = re.search(
#         r"\b(?:whole team|entire team|all team members|"
#         r"multiple users|many users|all users)\b"
#         r".{0,40}\b(?:not affected|not impacted|unaffected)\b",
#         text,
#         re.IGNORECASE,
#     )

#     if team_unaffected:
#         return "Medium", 0.55

#     # Evaluate the strongest impact rules first.
#     for severity, pattern, confidence in _SEVERITY_RULES:
#         for match in pattern.finditer(text):
#             if not _is_negated_match(text, match.start()):
#                 return severity, confidence

#     # Low-confidence fallback: the impact is not clear from the text.
#     return "Medium", 0.55



# def classify(
#     subject: str | None,
#     description: str,
#     department: str | None = None,
# ) -> dict[str, Any]:
#     """Return the category, severity, confidence, and priority."""
#     text = " ".join(
#         part for part in (subject or "", description or "") if part
#     ).strip()

#     result = classify_category(text)

#     severity, severity_confidence = classify_severity(text)

#     result.update(
#         {
#             "severity": severity,
#             "severity_confidence": severity_confidence,
#             "priority": _PRIORITY_BY_SEVERITY.get(severity, "Review Required"),
#         }
#     )

#     return result


# """Production-facing category and severity classifier."""

# from pathlib import Path
# from typing import Any
# import re
# import time

# import joblib
# import numpy as np

# from .subcategory_rules import high_confidence_category, predict_subcategory


# DEFAULT_MODEL_PATH = (
#     Path(__file__).resolve().parent / "models" / "category_model.joblib"
# )
# MIN_WORDS = 3
# MIN_CONFIDENCE = 0.55

# _PRIORITY_BY_SEVERITY = {
#     "Critical": "P1",
#     "High": "P2",
#     "Medium": "P3",
#     "Low": "P4",
# }

# CRITICAL_DEPARTMENTS = {"IT", "FINANCE"}

# _PRIORITY_ESCALATION = {
#     "P4": "P3",
#     "P3": "P2",
#     "P2": "P1",
#     "P1": "P1",
# }


# def load_artifact(
#     model_path: str | Path = DEFAULT_MODEL_PATH,
# ) -> dict[str, Any]:
#     """Load the exported category vectorizer and classifier."""
#     return joblib.load(model_path)


# def classify_category(
#     text: str,
#     model_path: str | Path = DEFAULT_MODEL_PATH,
# ) -> dict[str, Any]:
#     """Classify a ticket into a category and subcategory."""
#     text = str(text or "").strip()

#     if not text or len(re.findall(r"\b\w+\b", text)) < MIN_WORDS:
#         return {
#             "category": "Unknown",
#             "sub_category": "Other",
#             "category_confidence": 0.0,
#         }

#     rule_category = high_confidence_category(text)

#     if rule_category is not None:
#         return {
#             "category": rule_category,
#             "sub_category": predict_subcategory(text, rule_category),
#             "category_confidence": 0.99,
#         }

#     artifact = load_artifact(model_path)
#     vectorizer = artifact["vectorizer"]
#     model = artifact["model"]

#     features = vectorizer.transform([text])
#     probabilities = model.predict_proba(features)[0]

#     index = int(np.argmax(probabilities))
#     category = str(model.classes_[index])
#     confidence = float(probabilities[index])

#     if confidence < MIN_CONFIDENCE:
#          return {
#             "category": category,
#             "sub_category": predict_subcategory(text, category),
#             "category_confidence": round(confidence, 4),
#             "category_needs_review": True,
#     }

#     return {
#         "category": category,
#         "sub_category": predict_subcategory(text, category),
#         "category_confidence": round(confidence, 4),
#     }


# # Rules are checked from highest to lowest impact.
# _SEVERITY_RULES = (
#     (
#         "Critical",
#         re.compile(
#             r"\b(?:"
#             r"company[- ]wide|organisation[- ]wide|organization[- ]wide|"
#             r"all users|everyone|entire company|"
#             r"major security incident|critical security incident|"
#             r"confirmed data breach|ransomware|"
#             r"production (?:system )?(?:is )?down|"
#             r"complete(?:ly)? unavailable|"
#             r"critical business system|"
#             r"widespread outage|major data loss"
#             r")\b",
#             re.IGNORECASE,
#         ),
#         0.92,
#     ),
#     (
#         "High",
#         re.compile(
#             r"\b(?:"
#             r"multiple users|many users|entire team|whole team|"
#             r"all team members|service unavailable|"
#             r"major disruption|business operations|"
#             r"system outage|outage|cannot access important|"
#             r"down for (?:the )?team|multiple applications|"
#             r"several employees|multiple employees"
#             r")\b",
#             re.IGNORECASE,
#         ),
#         0.86,
#     ),
#     (
#         "Medium",
#         re.compile(
#             r"\b(?:"
#             r"individual user|one user|significant issue|workaround|"
#             r"unable to access|cannot access|can't access|"
#             r"blocked|intermittent|connection problems?|"
#             r"slow application|application is slow|"
#             r"slow performance|performance degradation|"
#             r"authentication failed|login failure"
#             r")\b",
#             re.IGNORECASE,
#         ),
#         0.78,
#     ),
#     (
#         "Low",
#         re.compile(
#             r"\b(?:"
#             r"minor inconvenience|cosmetic|non[- ]urgent|"
#             r"routine request|software installation|"
#             r"how do i|how can i|general question|"
#             r"requesting information|seeking guidance|"
#             r"install approved software|approved software installation|"
#             r"could you explain|change my email signature"
#             r")\b",
#             re.IGNORECASE,
#         ),
#         0.82,
#     ),
# )


# def _is_negated_match(text: str, match_start: int) -> bool:
#     """Check whether an impact phrase is explicitly negated."""
#     preceding_text = text[max(0, match_start - 60):match_start]
#     following_text = text[match_start:match_start + 100]

#     preceding_negation = re.compile(
#         r"\b(?:not|no|never|without|isn't|is not|"
#         r"wasn't|was not|ruled out|no evidence of|not detected)"
#         r"(?:\s+\w+){0,5}\s*$",
#         re.IGNORECASE,
#     )

#     following_negation = re.compile(
#         r"^\s*(?:is\s+|was\s+|has\s+been\s+|were\s+|are\s+)?"
#         r"not\s+(?:affected|impacted|experiencing|experiencing any)",
#         re.IGNORECASE,
#     )

#     return bool(
#         preceding_negation.search(preceding_text)
#         or following_negation.search(following_text)
#     )


# def classify_severity(text: str) -> tuple[str, float]:
#     """Infer severity from impact and flag uncertain cases for review."""
#     text = str(text or "").strip().lower()

#     if not text:
#         return "Medium", 0.0

#     # A clearly negated critical issue is not automatically Critical.
#     if re.search(
#         r"\bnot\s+(?:a\s+)?critical issue\b",
#         text,
#         re.IGNORECASE,
#     ):
#         return "Medium", 0.55

#     # Unconfirmed security incidents require human review.
#     uncertain_security = re.search(
#         r"\b(?:potential|possible|suspected|alleged)\b.{0,100}"
#         r"\b(?:breach|ransomware|unauthori[sz]ed access|"
#         r"security incident|data exposure)\b"
#         r"|\b(?:may|might|could)\s+have\b.{0,80}"
#         r"\b(?:exposed|compromised|breached)\b",
#         text,
#         re.IGNORECASE,
#     )

#     if uncertain_security:
#         return "Unknown", 0.0
#         # A single-user connection timeout without evidence of wider impact is Medium.
#     if (
#         re.search(r"\b(?:connection|connectivity)\s+timed?\s*out\b|\bconnection timeout\b", text)
#         and not re.search(
#             r"\b(?:all users|multiple users|whole team|entire company|"
#             r"production down|company-wide outage)\b",
#             text,
#         )
#     ):
#         return "Medium", 0.75
#     # Informational requests are Low unless an active incident is described.
#     informational_request = re.search(
#         r"\b(?:could you explain|how do i|how can i|"
#         r"general question|seeking guidance|requesting information|"
#         r"change my email signature|install approved software|"
#         r"routine request|minor inconvenience|cosmetic issue)\b",
#         text,
#         re.IGNORECASE,
#     )

#     active_incident = re.search(
#         r"\b(?:outage|system is down|production down|"
#         r"service unavailable|data breach|ransomware|"
#         r"unauthori[sz]ed access|security incident|"
#         r"data loss|cannot access|can't access|unable to access)\b",
#         text,
#         re.IGNORECASE,
#     )

#     if informational_request and not active_incident:
#         return "Low", 0.82

#     # Use explicit impact rules, highest severity first.
#     for severity, pattern, confidence in _SEVERITY_RULES:
#         for match in pattern.finditer(text):
#             if not _is_negated_match(text, match.start()):
#                 return severity, confidence

#     # Unclear impact should be reviewed rather than guessed.
#     return "Unknown", 0.0


# def classify(
#     subject: str | None,
#     description: str,
#     department: str | None = None,
# ) -> dict[str, Any]:
#     """Return category, severity, priority, confidence, and processing time."""
#     start_time = time.perf_counter()

#     text = " ".join(
#         part
#         for part in (subject or "", description or "")
#         if part
#     ).strip()

#     result = classify_category(text)
#     severity, severity_confidence = classify_severity(text)

#     # Unknown severity is routed for review.
#     needs_human_review = severity == "Unknown"

#     if needs_human_review:
#     # Temporary fallback; do not escalate an unconfirmed severity.
#         priority = "P3"
#     else:
#         priority = _PRIORITY_BY_SEVERITY[severity]

#     # Escalate one level for IT and Finance departments.
#     department_name = str(department or "").strip().upper()

#     if (
#         not needs_human_review
#         and department_name in CRITICAL_DEPARTMENTS
#         and priority in _PRIORITY_ESCALATION
#     ):
#         priority = _PRIORITY_ESCALATION[priority]
#     result.update(
#         {
#             "severity": severity,
#             "needs_human_review": needs_human_review,
#             "severity_confidence": severity_confidence,
#             "priority": priority,
#             "processing_ms": round(
#                 (time.perf_counter() - start_time) * 1000,
#                 2,
#             ),
#         }
#     )

#     return result


"""Production-facing category and severity classifier."""

from pathlib import Path
from typing import Any
import re
import time

import joblib
import numpy as np

from .subcategory_rules import high_confidence_category, predict_subcategory


DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parent / "models" / "category_model.joblib"
)
MIN_WORDS = 3
MIN_CONFIDENCE = 0.55

_PRIORITY_BY_SEVERITY = {
    "Critical": "P1",
    "High": "P2",
    "Medium": "P3",
    "Low": "P4",
}

CRITICAL_DEPARTMENTS = {"IT", "FINANCE"}

_PRIORITY_ESCALATION = {
    "P4": "P3",
    "P3": "P2",
    "P2": "P1",
    "P1": "P1",
}


def load_artifact(
    model_path: str | Path = DEFAULT_MODEL_PATH,
) -> dict[str, Any]:
    """Load the exported category model artifact."""
    return joblib.load(model_path)


def classify_category(
    text: str,
    model_path: str | Path = DEFAULT_MODEL_PATH,
) -> dict[str, Any]:
    """Classify a ticket into a category and subcategory."""
    text = str(text or "").strip()
    if not text or len(re.findall(r"\b\w+\b", text)) < MIN_WORDS:
        return {
            "category": "Unknown",
            "sub_category": "Other",
            "category_confidence": 0.0,
            "category_needs_review": True,
        }

    rule_category = high_confidence_category(text)

    if rule_category is not None:
        return {
            "category": rule_category,
            "sub_category": predict_subcategory(text, rule_category),
            "category_confidence": 0.99,
        }

    artifact = load_artifact(model_path)
    vectorizer = artifact["vectorizer"]
    model = artifact["model"]

    features = vectorizer.transform([text])
    probabilities = model.predict_proba(features)[0]

    index = int(np.argmax(probabilities))
    category = str(model.classes_[index])
    confidence = float(probabilities[index])
    result = {
        "category": category,
        "sub_category": predict_subcategory(text, category),
        "category_confidence": round(confidence, 4),
    }

    if confidence < MIN_CONFIDENCE:
        result["category_needs_review"] = True

    return result


# Rules are evaluated from highest to lowest impact.
_SEVERITY_RULES = (
    (
        "Critical",
        re.compile(
            r"\b(?:"
            r"company[- ]wide|organisation[- ]wide|organization[- ]wide|"
            r"all users|everyone|entire company|"
            r"major security incident|critical security incident|"
            r"confirmed data breach|ransomware|"
            r"production (?:system )?(?:is )?down|"
            r"complete(?:ly)? unavailable|"
            r"critical business system|widespread outage|major data loss"
            r")\b",
            re.IGNORECASE,
        ),
        0.92,
    ),
    (
        "High",
        re.compile(
            r"\b(?:"
            r"multiple users|many users|entire team|whole team|"
            r"all team members|service unavailable|major disruption|"
            r"business operations|system outage|outage|"
            r"cannot access important|down for (?:the )?team|"
            r"multiple applications|several employees|multiple employees"
            r")\b",
            re.IGNORECASE,
        ),
        0.86,
    ),
    (
        "Medium",
        re.compile(
            r"\b(?:"
            r"individual user|one user|significant issue|workaround|"
            r"unable to access|cannot access|can't access|blocked|"
            r"intermittent|connection problems?|connection timeout|"
            r"connection timed out|connectivity timed out|"
            r"slow application|application is slow|slow performance|"
            r"performance degradation|authentication failed|login failure"
            r")\b",
            re.IGNORECASE,
        ),
        0.78,
    ),
    (
        "Low",
        re.compile(
            r"\b(?:"
            r"minor inconvenience|cosmetic|non[- ]urgent|routine request|"
            r"software installation|how do i|how can i|general question|"
            r"requesting information|seeking guidance|"
            r"install approved software|approved software installation|"
            r"could you explain|change my email signature"
            r")\b",
            re.IGNORECASE,
        ),
        0.82,
    ),
)


def _is_negated_match(text: str, match_start: int) -> bool:
    """Check whether an impact phrase is explicitly negated."""
    preceding_text = text[max(0, match_start - 60):match_start]
    following_text = text[match_start:match_start + 100]

    preceding_negation = re.compile(
        r"\b(?:not|no|never|without|isn't|is not|"
        r"wasn't|was not|ruled out|no evidence of|not detected)"
        r"(?:\s+\w+){0,5}\s*$",
        re.IGNORECASE,
    )

    following_negation = re.compile(
        r"^\s*(?:is\s+|was\s+|has\s+been\s+|were\s+|are\s+)?"
        r"not\s+(?:affected|impacted|experiencing|experiencing any)",
        re.IGNORECASE,
    )

    return bool(
        preceding_negation.search(preceding_text)
        or following_negation.search(following_text)
    )


def classify_severity(text: str) -> tuple[str, float]:
    """Infer severity from impact; retain uncertain cases for human review."""
    text = str(text or "").strip().lower()

    if not text:
        return "Unknown", 0.0

    # Do not interpret a negated critical label as a critical incident.
    if re.search(r"\bnot\s+(?:a\s+)?critical issue\b", text):
        return "Medium", 0.55

    # Unconfirmed security incidents require human review.
    uncertain_security = re.search(
        r"\b(?:potential|possible|suspected|alleged)\b.{0,100}"
        r"\b(?:breach|ransomware|unauthori[sz]ed access|"
        r"security incident|data exposure)\b"
        r"|\b(?:may|might|could)\s+have\b.{0,80}"
        r"\b(?:exposed|compromised|breached)\b",
        text,
        re.IGNORECASE,
    )

    if uncertain_security:
        return "Unknown", 0.0

    # Routine password resets are Low unless an active security incident is described.
    routine_password_reset = re.search(
        r"\b(?:password reset|reset my password|forgot my password|"
        r"password recovery|unlock my account|locked out of my account)\b",
        text,
        re.IGNORECASE,
    )
    active_security_incident = re.search(
        r"\b(?:unauthori[sz]ed access|confirmed data breach|"
        r"ransomware|active security incident|data exposure)\b",
        text,
        re.IGNORECASE,
    )
    if routine_password_reset and not active_security_incident:
        return "Low", 0.82

    # Informational requests are Low unless an active incident is described.
    informational_request = re.search(
        r"\b(?:could you explain|how do i|how can i|"
        r"general question|seeking guidance|requesting information|"
        r"change my email signature|install approved software|"
        r"routine request|minor inconvenience|cosmetic issue)\b",
        text,
        re.IGNORECASE,
    )

    active_incident = re.search(
        r"\b(?:outage|system is down|production down|"
        r"service unavailable|data breach|ransomware|"
        r"unauthori[sz]ed access|security incident|data loss|"
        r"cannot access|can't access|unable to access)\b",
        text,
        re.IGNORECASE,
    )

    if informational_request and not active_incident:
        return "Low", 0.82

    # Specific, common limited-impact incidents.
    limited_impact = re.search(
        r"\b(?:printer jam(?:med)?|printer is jammed|"
        r"wi[- ]?fi is very slow|wi[- ]?fi is slow|"
        r"slow wi[- ]?fi|slow network connection)\b",
        text,
        re.IGNORECASE,
    )

    wider_impact = re.search(
        r"\b(?:all users|multiple users|many users|"
        r"whole team|entire team|several employees|"
        r"multiple employees|company[- ]wide|"
        r"production (?:system )?(?:is )?down|"
        r"widespread outage|service unavailable)\b",
        text,
        re.IGNORECASE,
    )

    if limited_impact and not wider_impact:
        return "Medium", 0.75

    # A single-user connection timeout is Medium without evidence of wider impact.
    connection_timeout = re.search(
        r"\b(?:connection|connectivity)\s+timed?\s*out\b|"
        r"\bconnection timeout\b",
        text,
        re.IGNORECASE,
    )

    if connection_timeout and not wider_impact:
        return "Medium", 0.75

    # Apply the impact rules from highest to lowest severity.
    for severity, pattern, confidence in _SEVERITY_RULES:
        for match in pattern.finditer(text):
            if not _is_negated_match(text, match.start()):
                return severity, confidence

    # Never invent a severity when the ticket provides insufficient evidence.
    return "Unknown", 0.0


def classify(
    subject: str | None,
    description: str,
    department: str | None = None,
) -> dict[str, Any]:
    """Return category, severity, priority, confidence, and processing time."""
    start_time = time.perf_counter()

    text = " ".join(
        part
        for part in (subject or "", description or "")
        if part
    ).strip()

    result = classify_category(text)

    severity, severity_confidence = classify_severity(text)

    needs_human_review = (
        severity == "Unknown"
        or result.get("category") == "Unknown"
        or result.get("category_needs_review", False)
    )

    # Unknown severity receives a temporary P3 pending human review.
    if severity == "Unknown":
        priority = "P3"
    else:
        priority = _PRIORITY_BY_SEVERITY[severity]

    # Escalate one level for IT and Finance only when severity is known.
    department_name = str(department or "").strip().upper()

    if (
        severity != "Unknown"
        and department_name in CRITICAL_DEPARTMENTS
    ):
        priority = _PRIORITY_ESCALATION[priority]

    result.update(
        {
            "severity": severity,
            "needs_human_review": needs_human_review,
            "severity_confidence": severity_confidence,
            "priority": priority,
            "processing_ms": round(
                (time.perf_counter() - start_time) * 1000,
                2,
            ),
        }
    )

    return result
