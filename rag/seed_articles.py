"""Create the reviewed starter article set from the FAQ themes.

This is intentionally deterministic so the starter set can be regenerated after
the PDF-derived topics are edited. The generated Markdown files are the runtime
source of truth; this helper is not used by indexing.
"""

from pathlib import Path

from . import config


TOPICS = {
    "Network": [
        ("No internet connection", "no internet, connectivity, offline"),
        ("Wi-Fi keeps disconnecting", "wifi, wireless, disconnecting"),
        ("Slow Wi-Fi connection", "wifi, wireless, slow connection"),
        ("DNS lookup failure", "dns, name resolution, website"),
        ("Network cable not detected", "ethernet, cable, network adapter"),
        ("Network authentication failure", "wifi, authentication, network password"),
        ("Shared drive unavailable", "shared drive, network share, access"),
        ("Network outage for a team", "network outage, team, unavailable"),
    ],
    "VPN": [
        ("VPN connection timed out", "vpn, timeout, remote access"),
        ("VPN authentication failed", "vpn, authentication, login"),
        ("VPN keeps disconnecting", "vpn, disconnecting, tunnel"),
        ("VPN client will not open", "vpn, client, launch"),
        ("VPN profile cannot be imported", "vpn, profile, configuration"),
        ("VPN works in the office but not at home", "vpn, home network, remote access"),
        ("VPN connection is slow", "vpn, slow, performance"),
        ("VPN cannot reach an internal application", "vpn, internal application, routing"),
    ],
    "Software": [
        ("Application will not start", "application, launch, software"),
        ("Application crashes repeatedly", "application, crash, software"),
        ("Application freezes", "application, freeze, not responding"),
        ("Software installation failed", "software, installation, error"),
        ("Software update failed", "software, update, installation"),
        ("Application shows a blank screen", "application, blank screen, display"),
        ("Application is slow", "application, slow, performance"),
        ("Application compatibility problem", "application, compatibility, operating system"),
    ],
    "Hardware": [
        ("Laptop or desktop will not power on", "hardware, power, startup"),
        ("Computer starts but screen is black", "hardware, display, black screen"),
        ("Computer is stuck at the manufacturer logo", "hardware, startup, boot"),
        ("Computer restarts during startup", "hardware, restart, boot"),
        ("Battery will not charge", "hardware, battery, charging"),
        ("Printer is jammed", "hardware, printer, paper jam"),
        ("Keyboard or mouse is not responding", "hardware, keyboard, mouse, peripheral"),
        ("Monitor has no signal", "hardware, monitor, display"),
    ],
    "Password Reset": [
        ("Forgotten password", "password, reset, account"),
        ("Account is locked", "password, locked account, access"),
        ("Password reset link expired", "password, reset link, account"),
        ("Password change is rejected", "password, change, policy"),
        ("Multi-factor authentication code is unavailable", "mfa, authentication, account"),
        ("New password does not work", "password, login, authentication"),
        ("User cannot unlock an account", "account unlock, password, access"),
        ("Shared account access request", "shared account, access, authorization"),
    ],
    "Email": [
        ("Email will not send", "email, send, outbox"),
        ("Email will not arrive", "email, receive, mailbox"),
        ("Email is stuck in the outbox", "email, outbox, send"),
        ("Mailbox is full", "email, mailbox, storage"),
        ("Outlook will not open", "email, outlook, launch"),
        ("Email is not synchronizing", "email, synchronization, outlook"),
        ("Unexpected email sign-in prompt", "email, outlook, login"),
        ("Email attachment cannot be opened", "email, attachment, file"),
    ],
    "Security": [
        ("Suspicious phishing email", "security, phishing, email"),
        ("Suspected malware alert", "security, malware, endpoint"),
        ("Unauthorized sign-in notification", "security, unauthorized access, login"),
        ("Possible data breach", "security, breach, data exposure"),
        ("Lost device security response", "security, lost device, incident"),
        ("Suspicious attachment", "security, attachment, malware"),
        ("Ransomware warning", "security, ransomware, incident"),
        ("Sensitive information sent to the wrong recipient", "security, data exposure, email"),
    ],
}


PROCEDURES = {
    "Network": [
        "Record whether the problem affects one device or multiple users.",
        "Confirm that cables, wireless status, and airplane mode are correct.",
        "Reconnect using the approved network and retry the affected service.",
        "Note the exact error message, location, and time of the failure.",
        "Use only organization-approved diagnostics and avoid changing network policy settings.",
    ],
    "VPN": [
        "Confirm that the device has working internet access outside the VPN.",
        "Close and reopen the approved VPN client once.",
        "Verify the organization-provided profile and sign-in method.",
        "Retry the connection and record the exact error or timeout message.",
        "Check whether the problem affects other remote users before escalating.",
    ],
    "Software": [
        "Record the application name, version, exact error, and recent changes.",
        "Save work, close other applications, and restart the affected application.",
        "Confirm that the device has sufficient storage and a supported operating system.",
        "Use only the organization-approved repair, update, or reinstall procedure.",
        "Test once more and preserve any diagnostic log requested by support.",
    ],
    "Hardware": [
        "Record status lights, sounds, displayed messages, and when the problem began.",
        "Check the approved power adapter, cable, outlet, and external connections.",
        "Disconnect nonessential peripherals and retry the safe manufacturer power-reset procedure.",
        "Use built-in or vendor diagnostics without changing unrelated firmware settings.",
        "Protect the device and its data while waiting for an authorized hardware review.",
    ],
    "Password Reset": [
        "Confirm the affected username and the service where sign-in fails.",
        "Use the organization-approved password reset or account-unlock page.",
        "Complete the approved identity and multi-factor verification steps.",
        "Choose a new password that meets the organization policy and test it once.",
        "Do not share passwords or verification codes with anyone requesting them unexpectedly.",
    ],
    "Email": [
        "Record the sender or recipient, time, subject, and exact error message.",
        "Confirm that the device has network access and the mailbox is not full.",
        "Retry from the approved web or desktop mail client as appropriate.",
        "Check the outbox, message size, attachment type, and recipient address.",
        "Avoid opening unexpected attachments and preserve headers if support requests them.",
    ],
    "Security": [
        "Stop interacting with the suspicious message, attachment, link, or device.",
        "Do not disable endpoint protection, bypass MFA, or delete evidence.",
        "Record the sender, time, device, alert text, and any action already taken.",
        "Use the organization-approved reporting or incident channel.",
        "Follow security-team instructions and change credentials only through approved procedures.",
    ],
}


def create_articles() -> int:
    count = 0
    for category, topics in TOPICS.items():
        folder = config.KB_DIR / category.lower().replace(" ", "-")
        folder.mkdir(parents=True, exist_ok=True)
        for title, keywords in topics:
            slug = title.lower().replace("/", " ").replace(" ", "-")
            slug = "-".join(part for part in slug.split("-") if part)
            steps = PROCEDURES[category]
            body = "\n".join(
                [
                    f"Symptoms: The user reports {title.lower()}.",
                    "",
                    "Steps:",
                    *[f"{i}. {step}" for i, step in enumerate(steps, 1)],
                    "",
                    "Escalate if: the issue continues after these checks, affects multiple users, or involves data loss, physical danger, suspected compromise, or an unsupported change.",
                    "",
                ]
            )
            content = f"---\ntitle: {title}\ncategory: {category}\nkeywords: {keywords}\n---\n{body}"
            (folder / f"{slug}.md").write_text(content, encoding="utf-8")
            count += 1
    return count


if __name__ == "__main__":
    print(f"Created {create_articles()} starter articles in {config.KB_DIR}")
