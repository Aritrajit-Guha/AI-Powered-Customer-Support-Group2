"""The bridge between the backend and the AI models.

Sample Contract:

    classify(subject, description, department) -> {
        "category": "VPN",
        "sub_category": "Timeout",
        "category_confidence": 0.92,
        "severity": "High",
        "severity_confidence": 0.88,
        "priority": "P2",
    }

HOW IT WORKS
- If   ml/classifier.py present ,
  the backend uses it automatically - no code change needed here.
- Until then, a simple keyword-based STUB below is used, so the whole
  backend, tests and UI work today.
"""
import sys
from pathlib import Path

# Repo root importable so  `import ml.classifier`  works.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.append(str(_ROOT))

_real_classify = None
try:
    from ml.classifier import classify as _real_classify  # Person 3's real function
except ImportError:
    _real_classify = None
except Exception as exc:  # file exists but is broken (e.g. model file missing)
    print(f"[classifier] WARNING: ml/classifier.py found but failed to load: {exc}")
    print("[classifier] Falling back to the stub.")
    _real_classify = None


def classifier_in_use() -> str:
    return "real-model" if _real_classify else "stub"


_KEYWORDS = [
    ("VPN", ["vpn", "anyconnect", "globalprotect"]),
    ("Password Reset", ["password", "locked out", "account locked", "forgot", "reset my"]),
    ("Email", ["email", "outlook", "mailbox", "inbox", "smtp"]),
    ("Security", ["phishing", "malware", "virus", "breach", "suspicious", "hacked", "ransomware"]),
    ("Network", ["wifi", "wi-fi", "network", "internet", "lan", "dns", "router"]),
    ("Hardware", ["printer", "laptop", "keyboard", "monitor", "mouse", "screen", "battery"]),
    ("Software", ["install", "software", "license", "crash", "update", "application", "app "]),
]
_CRITICAL_WORDS = ["breach", "ransomware", "outage", "all users", "data loss", "everyone", "production down"]
_HIGH_WORDS = ["urgent", "cannot work", "can't work", "not working", "down", "blocked", "asap"]
_PRIORITY = {"Critical": "P1", "High": "P2", "Medium": "P3", "Low": "P4"}


def _stub_classify(subject, description, department):
    text = f"{subject or ''} {description or ''}".lower()
    category = "Software"
    for name, words in _KEYWORDS:
        if any(w in text for w in words):
            category = name
            break
    if any(w in text for w in _CRITICAL_WORDS):
        severity = "Critical"
    elif any(w in text for w in _HIGH_WORDS):
        severity = "High"
    elif len(text.split()) < 6:
        severity = "Low"
    else:
        severity = "Medium"
    return {
        "category": category,
        "sub_category": "General",
        "category_confidence": 0.5,
        "severity": severity,
        "severity_confidence": 0.5,
        "priority": _PRIORITY[severity],
    }


def classify(subject, description, department):
    if _real_classify:
        return _real_classify(subject, description, department)
    return _stub_classify(subject, description, department)
