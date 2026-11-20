
from unittest.mock import patch

from rag.pipeline import resolve


def test_resolve_generates_response_from_relevant_article():
    article = {
        "slug": "vpn-test",
        "title": "VPN Troubleshooting",
        "category": "VPN",
        "score": 0.90,
        "content": (
            "Steps:\n"
            "1. Check your internet connection.\n"
            "2. Restart the VPN client.\n"
            "Escalate if: the issue continues."
        ),
    }

    with patch("rag.pipeline.search_kb", return_value=[article]):
        result = resolve(
            "VPN timeout",
            "My VPN connection keeps timing out.",
            "VPN",
        )

    assert result["needs_human_review"] is False
    assert result["mode"] == "default"
    assert result["confidence"] >= 0.60
    assert len(result["steps"]) == 2
    assert "VPN Troubleshooting" in result["response_text"]
    assert len(result["trace"]) == 4


def test_resolve_requests_human_review_when_no_article_found():
    with patch("rag.pipeline.search_kb", return_value=[]):
        result = resolve(
            "Unknown issue",
            "Something is not working.",
            "Unknown",
        )

    assert result["confidence"] == 0.0
    assert result["mode"] == "human_review"
    assert result["needs_human_review"] is True
    assert result["steps"] == []
    assert result["sources"] == []
    assert "support engineer will review" in result["response_text"]


def test_resolve_requests_human_review_for_low_confidence():
    article = {
        "slug": "vpn-test",
        "title": "VPN Troubleshooting",
        "category": "VPN",
        "score": 0.40,
        "content": "Steps:\n1. Check your internet connection.",
    }

    with patch("rag.pipeline.search_kb", return_value=[article]):
        result = resolve(
            "VPN timeout",
            "My VPN connection keeps timing out.",
            "VPN",
        )

    assert result["needs_human_review"] is True
    assert result["mode"] == "human_review"
    assert result["steps"] == []
