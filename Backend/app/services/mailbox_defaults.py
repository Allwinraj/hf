from __future__ import annotations

from typing import Any

# Demo Gmail only. Shown on the ingest node. Do not put these in .env or manifest.yml.
MAILBOX_APP_NAME = "nexus"
MAILBOX_ADDRESS = "eyindia.nexus@gmail.com"
MAILBOX_APP_PASSWORD = "kjcpuaarggiddtwx"
MAILBOX_FOLDER = "INBOX"
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def mailbox_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = {
        "mode": "mailbox",
        "app_name": MAILBOX_APP_NAME,
        "imap_host": IMAP_HOST,
        "imap_port": IMAP_PORT,
        "imap_tls": True,
        "username": MAILBOX_ADDRESS,
        "password": MAILBOX_APP_PASSWORD,
        "folder": MAILBOX_FOLDER,
        "unread_only": True,
        "smtp_host": SMTP_HOST,
        "smtp_port": SMTP_PORT,
        "smtp_starttls": True,
        "from_address": MAILBOX_ADDRESS,
    }
    if overrides:
        for key, value in overrides.items():
            if value is not None and value != "":
                config[key] = value
    password = str(config.get("password") or "").replace(" ", "")
    config["password"] = password
    return config
