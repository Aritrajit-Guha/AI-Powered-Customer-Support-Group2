from agents.recurring import find_recurring, signature


def test_recurring_detector_groups_repeated_issue_signatures():
    tickets = [
        {"ticket_id": 1, "subject": "VPN timeout", "description": "VPN connection timeout", "category": "VPN"},
        {"ticket_id": 2, "subject": "VPN timeout", "description": "VPN connection timeout", "category": "VPN"},
        {"ticket_id": 3, "subject": "VPN timeout", "description": "VPN connection timeout", "category": "VPN"},
        {"ticket_id": 4, "subject": "Printer jam", "description": "paper jam", "category": "Hardware"},
    ]
    result = find_recurring(tickets)
    assert len(result) == 1
    assert result[0]["category"] == "VPN"
    assert result[0]["occurrence_count"] == 3
    assert result[0]["sample_ticket_ids"] == [1, 2, 3]


def test_signature_is_stable_for_same_issue_words():
    assert signature("VPN timeout", "VPN connection timeout", "VPN") == signature(
        "Please help: VPN connection timeout", "The issue is a VPN timeout", "VPN"
    )
