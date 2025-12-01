from __future__ import annotations

import imaplib
import os
from typing import List, Tuple, Optional

IMAP_HOST = "imap.gmail.com"


def get_imap_credentials():
    email_addr = os.environ.get("AO3TRACKER_EMAIL")
    password = os.environ.get("AO3TRACKER_IMAP_PASSWORD")
    if not email_addr or not password:
        raise RuntimeError(
            "AO3TRACKER_EMAIL and/or AO3TRACKER_IMAP_PASSWORD not set in environment."
        )
    return email_addr, password


def connect_imap() -> imaplib.IMAP4_SSL:
    email_addr, password = get_imap_credentials()
    mail = imaplib.IMAP4_SSL(IMAP_HOST)
    mail.login(email_addr, password)
    return mail


def select_ao3_mailbox(mail: imaplib.IMAP4_SSL) -> str:
    """
    Try to select the AO3 label as a mailbox.
    If that fails, fall back to INBOX.
    Returns the name of the selected mailbox.
    """
    # Try direct AO3 label as Gmail "folder"
    status, _ = mail.select('"AO3"')
    if status == "OK":
        return "AO3"

    # Fall back to INBOX
    status, _ = mail.select("INBOX")
    if status != "OK":
        raise RuntimeError("Could not select INBOX mailbox.")
    return "INBOX"


def fetch_message_ids(mail: imaplib.IMAP4_SSL, mailbox: str, limit: Optional[int] = 100) -> List[bytes]:
    """
    Return a list of message IDs (as bytes) for AO3 messages.
    If we're in INBOX, filter by FROM address.
    
    Args:
        limit: Maximum number of messages to return. If None, returns all messages.
    """
    if mailbox == "AO3":
        status, data = mail.search(None, "ALL")
    else:
        # fallback: AO3 emails usually come from archiveofourown.org domain
        status, data = mail.search(None, '(FROM "archiveofourown.org")')

    if status != "OK":
        raise RuntimeError("IMAP search failed.")

    id_list = data[0].split()
    if not id_list:
        return []

    # If limit is None, return all messages. Otherwise take last `limit` messages (most recent)
    if limit is None:
        return id_list
    return id_list[-limit:]


def fetch_raw_message(mail: imaplib.IMAP4_SSL, msg_id: bytes) -> bytes:
    status, msg_data = mail.fetch(msg_id, "(RFC822)")
    if status != "OK":
        raise RuntimeError(f"Failed to fetch message ID {msg_id!r}")
    # msg_data is a list of (part_header, part_body) tuples
    return msg_data[0][1]
