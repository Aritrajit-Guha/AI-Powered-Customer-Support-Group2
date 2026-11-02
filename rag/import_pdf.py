"""Import the attached 300-question FAQ as exact Markdown retrieval records."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from . import config
from .article_store import slugify


DEFAULT_PDF = Path.home() / "Downloads" / "IT_Hardware_Software_Troubleshooting_FAQ_300_QA (1).pdf"
SAFETY_NOTE = (
    "Safety note: These are general first-line checks. Do not open equipment, "
    "alter firmware, change corporate network or security settings, bypass MFA, "
    "disable endpoint protection, or modify production data without authorization."
)

SUPPLEMENTAL_ARTICLES = {
    "Security": [
        ("Suspicious sign-in alert", "security, suspicious login, account", [
            "Do not approve an unexpected sign-in or MFA prompt.",
            "Record the alert time, device, location, and application.",
            "Change the password through the approved account portal if instructed.",
            "Review active sessions only through the approved security page.",
            "Report the alert to the security team using the approved channel.",
        ]),
        ("Phishing link clicked", "security, phishing, link", [
            "Stop interacting with the message and do not enter more information.",
            "Record the message, sender, link, and approximate click time.",
            "Disconnect from the network only if instructed by the security team.",
            "Use the approved incident-reporting workflow.",
            "Follow security instructions for credential review or reset.",
        ]),
        ("Malware alert on a workstation", "security, malware, endpoint", [
            "Stop using the affected workstation for nonessential activity.",
            "Do not disable endpoint protection or delete alert evidence.",
            "Record the alert name, device, user, and time.",
            "Use the approved security reporting channel.",
            "Wait for authorized instructions before reconnecting or cleaning the device.",
        ]),
        ("Suspicious email attachment", "security, phishing, attachment", [
            "Do not open, forward, or reply to the attachment.",
            "Record the sender, subject, filename, and received time.",
            "Report the message through the approved mail security control.",
            "If it was opened, state exactly what happened and when.",
            "Follow security-team instructions and preserve the message as evidence.",
        ]),
        ("Possible ransomware activity", "security, ransomware, malware", [
            "Stop using the device and do not rename, delete, or restore files.",
            "Do not pay a demand or contact an attacker.",
            "Record the visible message, device name, and time.",
            "Contact the incident-response team immediately through the approved channel.",
            "Follow containment instructions from authorized responders.",
        ]),
        ("Lost company device", "security, lost device, incident", [
            "Report the loss immediately with the device and user details.",
            "Do not attempt to track or recover the device using unapproved tools.",
            "Ask the authorized team to review account and device protections.",
            "Change credentials only through approved procedures if instructed.",
            "Record the last known location and time without sharing sensitive data publicly.",
        ]),
        ("Sensitive data sent to the wrong recipient", "security, data exposure, email", [
            "Do not forward the message or attempt an unauthorized recall.",
            "Record the recipients, data type, time, and delivery method.",
            "Notify the security or privacy team immediately.",
            "Follow instructions about recipient contact and evidence preservation.",
            "Do not delete records unless authorized.",
        ]),
        ("Unauthorized access suspected", "security, unauthorized access, incident", [
            "Stop making changes to the affected account or system.",
            "Record alerts, timestamps, devices, and unusual activity.",
            "Use the approved incident-reporting channel immediately.",
            "Preserve logs and messages as directed by responders.",
            "Change credentials only through an approved response procedure.",
        ]),
        ("Security software disabled unexpectedly", "security, endpoint protection, malware", [
            "Do not continue sensitive work on the affected device.",
            "Record the protection status, device name, and time observed.",
            "Do not install replacement security tools without authorization.",
            "Contact the security or endpoint-management team.",
            "Follow authorized remediation and verification steps.",
        ]),
        ("Unexpected MFA prompt", "security, MFA, authentication", [
            "Deny the prompt if you did not initiate the sign-in.",
            "Do not share the code or approve another prompt.",
            "Record the time and application shown.",
            "Report the event through the approved security process.",
            "Reset credentials only through the approved portal if instructed.",
        ]),
        ("Suspicious browser redirect", "security, browser, phishing", [
            "Close the suspicious tab without entering information.",
            "Record the visible address and the action that opened it.",
            "Do not install extensions or software suggested by the page.",
            "Run only approved endpoint checks if instructed.",
            "Report the event to the security team.",
        ]),
        ("Potential data exposure in a shared folder", "security, data exposure, access", [
            "Do not download, copy, or redistribute the exposed material.",
            "Record the folder, permission, time, and affected data type.",
            "Notify the data owner and security team through approved channels.",
            "Preserve evidence and access details.",
            "Wait for authorized instructions before changing permissions.",
        ]),
    ],
    "Email": [
        ("Email messages stuck in the outbox", "email, outbox, send", [
            "Confirm the device has network access.",
            "Check the recipient address and attachment size.",
            "Retry from the approved webmail client.",
            "Record the exact send error and time.",
            "Preserve message headers if support requests them.",
        ]),
        ("Mailbox quota reached", "email, mailbox, storage", [
            "Review the mailbox usage indicator.",
            "Remove only unneeded messages according to retention policy.",
            "Empty deleted or junk folders only when authorized.",
            "Retry sending or receiving a small test message.",
            "Contact support if the quota remains incorrect.",
        ]),
        ("Email synchronization stopped", "email, synchronization, outlook", [
            "Confirm network access and the account status.",
            "Check whether the approved webmail view has newer messages.",
            "Restart the approved mail client.",
            "Record the last successful synchronization time.",
            "Escalate without deleting the local mailbox profile.",
        ]),
        ("Email attachment cannot be opened", "email, attachment, file", [
            "Confirm the sender and expected file type.",
            "Do not open an unexpected or suspicious attachment.",
            "Save the message details without forwarding the file.",
            "Try the approved webmail client if the message is trusted.",
            "Report suspected malware to security.",
        ]),
        ("Outlook sign-in prompt repeats", "email, outlook, login", [
            "Confirm the device clock and network connection.",
            "Verify the account is not locked through the approved portal.",
            "Restart Outlook once.",
            "Record the prompt and error text.",
            "Do not delete credentials or profiles without support guidance.",
        ]),
        ("Email recipient cannot receive messages", "email, receive, delivery", [
            "Confirm the recipient address and message timestamp.",
            "Check for a bounce or delivery notification.",
            "Send a small test message without attachments.",
            "Record the delivery error and message ID.",
            "Escalate if multiple recipients are affected.",
        ]),
        ("Email rules moved a message unexpectedly", "email, mailbox, rules", [
            "Check the inbox, archive, junk, and configured folders.",
            "Review mail rules without deleting them.",
            "Record the message subject and destination folder.",
            "Use the approved mail-client repair guidance.",
            "Escalate suspected unauthorized rule changes to security.",
        ]),
        ("Email delivery is delayed", "email, delivery, delay", [
            "Record sender, recipient, subject, and send time.",
            "Check for a service advisory or bounce message.",
            "Avoid repeatedly sending sensitive duplicate messages.",
            "Send a harmless test message if appropriate.",
            "Escalate when the delay affects business-critical communication.",
        ]),
    ],
    "Password Reset": [
        ("Forgotten password", "password, reset, account", [
            "Use the approved password-reset portal.",
            "Complete the organization-approved identity verification.",
            "Set a unique password that meets policy.",
            "Test the new password once.",
            "Do not share the password or verification code.",
        ]),
        ("Account locked after failed attempts", "password, account locked, access", [
            "Stop repeated sign-in attempts.",
            "Use the approved account-unlock process.",
            "Complete the required identity verification.",
            "Check whether another device has an old saved password.",
            "Contact support if the account remains locked.",
        ]),
        ("Password reset link expired", "password, reset link, account", [
            "Request a new reset link from the approved portal.",
            "Use only the latest message from the trusted service.",
            "Complete identity verification promptly.",
            "Set and test the new password.",
            "Report unexpected reset messages to security.",
        ]),
        ("Password rejected by policy", "password, policy, reset", [
            "Read the approved password policy requirements.",
            "Choose a new password that does not reuse an old one.",
            "Avoid personal information and shared examples.",
            "Submit the change through the approved portal.",
            "Contact support without sending the password.",
        ]),
        ("MFA device unavailable during reset", "password, MFA, authentication", [
            "Do not bypass the MFA requirement.",
            "Use an approved alternate verification method if available.",
            "Report a lost or unavailable device through the approved channel.",
            "Complete identity verification with support.",
            "Register a replacement factor only through authorized procedures.",
        ]),
        ("New password does not work", "password, login, authentication", [
            "Confirm the username and service are correct.",
            "Wait for the stated synchronization period if applicable.",
            "Enter the new password without copying extra spaces.",
            "Stop after a small number of attempts.",
            "Use the approved recovery process if sign-in still fails.",
        ]),
        ("Account unlock request", "password, unlock, account", [
            "Confirm the affected account and business need.",
            "Submit the request through the approved access workflow.",
            "Complete manager or identity approval when required.",
            "Do not ask another person to share credentials.",
            "Record the request reference for follow-up.",
        ]),
        ("Suspicious password reset email", "password, phishing, reset", [
            "Do not click the reset link.",
            "Open the approved password portal directly if a reset is needed.",
            "Record the sender and message details.",
            "Report the message as suspected phishing.",
            "Change credentials only through the approved portal if instructed.",
        ]),
    ],
}


def extract_records(pdf_path: Path) -> list[tuple[int, str, str]]:
    text = " ".join((page.extract_text() or "") for page in PdfReader(pdf_path).pages)
    text = " ".join(text.split())
    records = re.findall(
        r"(\d{3})\.\s+(.*?)\s+Suggested answer:\s+(.*?)(?=\s+\d{3}\.\s+|\s+PART B|$)",
        text,
    )
    return [(int(number), question.strip(), answer.strip()) for number, question, answer in records]


def classify_question(question: str) -> str:
    """Assign a PDF question to the project's seven-category taxonomy."""
    text = question.lower()
    if re.search(r"phish|malware|virus|breach|ransomware|unauthori|suspicious|antivirus|security", text):
        return "Security"
    if "vpn" in text:
        return "VPN"
    if re.search(r"password|credential|account locked|forgot|reset", text):
        return "Password Reset"
    if re.search(r"email|mailbox|outlook|inbox|attachment|send|receive", text):
        return "Email"
    if re.search(r"wi[- ]?fi|internet|dns|network|router|connectivity", text):
        return "Network"
    if re.search(r"application|software|windows|browser|driver|update|install|file|excel|office", text):
        return "Software"
    return "Hardware"


def _write_article(category: str, slug: str, title: str, keywords: str, body: str) -> None:
    folder = config.KB_DIR / category.lower().replace(" ", "-")
    folder.mkdir(parents=True, exist_ok=True)
    content = f"---\ntitle: {title}\ncategory: {category}\nkeywords: {keywords}\n---\n{body.strip()}\n"
    (folder / f"{slug}.md").write_text(content, encoding="utf-8")


def import_pdf(pdf_path: str | Path = DEFAULT_PDF) -> int:
    pdf_path = Path(pdf_path)
    records = extract_records(pdf_path)
    if len(records) != 300:
        raise ValueError(f"Expected 300 FAQ records, extracted {len(records)}")

    config.KB_DIR.mkdir(parents=True, exist_ok=True)
    for path in config.KB_DIR.rglob("*.md"):
        if path.name.lower() != "readme.md":
            path.unlink()

    for ordinal, (number, question, answer) in enumerate(records, start=1):
        category = classify_question(question)
        slug = f"faq-{ordinal:03d}-{slugify(question)}"
        keywords = ", ".join(
            dict.fromkeys(
                [category.lower()]
                + [word.lower() for word in re.findall(r"[A-Za-z]{4,}", question)[:8]]
            )
        )
        body = "\n".join(
            (
                f"Question: {question}",
                "",
                f"Suggested answer: {answer}",
                "",
                "Steps:",
                "1. Follow the safe first-line checks described in the suggested answer.",
                "2. Record any exact error, status light, diagnostic code, or observed symptom.",
                "3. Stop and request authorized support if the issue persists or the check is unsafe.",
                "",
                f"Escalate if: the issue continues, affects multiple users, or involves physical danger, suspected compromise, or possible data loss.",
                "",
                SAFETY_NOTE,
                "",
            )
        )
        _write_article(category, slug, question, keywords, body)

    generated = 0
    for category, articles in SUPPLEMENTAL_ARTICLES.items():
        for title, keywords, steps in articles:
            body = "\n".join(
                (
                    f"Question: What should I do about {title.lower()}?",
                    "",
                    "Suggested answer: Follow the safe first-line checks below and use only organization-approved tools and procedures.",
                    "",
                    "Steps:",
                    *[f"{i}. {step}" for i, step in enumerate(steps, 1)],
                    "",
                    "Escalate if: the issue continues, affects multiple users, or involves suspected compromise, possible data loss, or an unsafe condition.",
                    "",
                    SAFETY_NOTE,
                )
            )
            _write_article(category, f"generated-{slugify(title)}", title, keywords, body)
            generated += 1
    return len(records) + generated


if __name__ == "__main__":
    print(f"Imported {import_pdf()} exact FAQ records into {config.KB_DIR}")
