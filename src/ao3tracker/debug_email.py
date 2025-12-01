#!/usr/bin/env python3
"""
Debug script to inspect a single email and see what the parser is getting.
"""

import email
import sys
from email.header import decode_header

from ao3tracker.imap_client import (
    connect_imap,
    select_ao3_mailbox,
    fetch_message_ids,
    fetch_raw_message,
)
from ao3tracker.ingest_imap import (
    decode_header_value,
    extract_body_from_email,
    parse_ao3_email,
)


def main():
    if len(sys.argv) > 1:
        try:
            msg_num = int(sys.argv[1])
        except ValueError:
            print(f"Usage: {sys.argv[0]} [message_number]")
            print("  If no number provided, will inspect the first message")
            sys.exit(1)
    else:
        msg_num = 1
    
    mail = connect_imap()
    try:
        mailbox = select_ao3_mailbox(mail)
        print(f"Selected mailbox: {mailbox}\n")
        
        msg_ids = fetch_message_ids(mail, mailbox, limit=10)
        if not msg_ids:
            print("No messages found.")
            return
        
        if msg_num > len(msg_ids):
            print(f"Only {len(msg_ids)} messages available. Using message {len(msg_ids)}")
            msg_num = len(msg_ids)
        
        msg_id = msg_ids[msg_num - 1]
        imap_seq = msg_id.decode("ascii", errors="ignore")
        
        print(f"Inspecting message {msg_num} (IMAP seq: {imap_seq})\n")
        print("=" * 80)
        
        raw = fetch_raw_message(mail, msg_id)
        msg = email.message_from_bytes(raw)
        
        # Headers
        subject = decode_header_value(msg.get("Subject", ""))
        date = msg.get("Date", "")
        msg_id_header = msg.get("Message-ID", "")
        
        print(f"Subject: {subject}")
        print(f"Date: {date}")
        print(f"Message-ID: {msg_id_header}")
        print(f"Content-Type: {msg.get_content_type()}")
        print(f"Is Multipart: {msg.is_multipart()}")
        print("\n" + "=" * 80)
        
        # Body
        body, content_type = extract_body_from_email(msg)
        print(f"\nBody Content Type: {content_type}")
        print(f"Body Length: {len(body)} characters")
        print("\n" + "=" * 80)
        print("First 1000 characters of body:")
        print("-" * 80)
        print(body[:1000])
        print("-" * 80)
        
        # Try parsing
        print("\n" + "=" * 80)
        print("Parsing attempt:")
        print("-" * 80)
        parsed = parse_ao3_email(body, content_type, subject)
        if parsed:
            print("✓ Successfully parsed!")
            print(f"  AO3 ID: {parsed['ao3_id']}")
            print(f"  Title: {parsed['title']}")
            print(f"  Author: {parsed['author']}")
            print(f"  URL: {parsed['url']}")
            print(f"  Chapter: {parsed['chapter_label']}")
            print(f"  Chapter Word Count: {parsed.get('chapter_word_count', 'N/A')}")
            print(f"  Work Word Count: {parsed.get('work_word_count', 'N/A')}")
        else:
            print("✗ Failed to parse")
            print("\nLooking for /works/ pattern in body:")
            import re
            work_matches = re.findall(r"/works/\d+", body)
            if work_matches:
                print(f"  Found {len(work_matches)} matches: {work_matches[:5]}")
            else:
                print("  No /works/ pattern found!")
        
        print("\n" + "=" * 80)
        
    finally:
        mail.logout()


if __name__ == "__main__":
    main()

