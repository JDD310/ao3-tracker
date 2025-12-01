from __future__ import annotations

import email
import hashlib
import re
from email.header import decode_header
from typing import Optional, Dict, Tuple

from bs4 import BeautifulSoup

from ao3tracker.imap_client import (
    connect_imap,
    select_ao3_mailbox,
    fetch_message_ids,
    fetch_raw_message,
)
from ao3tracker.db import (
    init_db,
    get_connection,
    has_processed_message,
    mark_processed_message,
    upsert_work_and_add_update,
    log_ingestion_start,
    log_ingestion_complete,
)


def decode_header_value(raw: Optional[str]) -> str:
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded = []
    for text, enc in parts:
        if isinstance(text, bytes):
            decoded.append(text.decode(enc or "utf-8", errors="ignore"))
        else:
            decoded.append(text)
    return "".join(decoded)


def extract_body_from_email(msg: email.message.Message) -> Tuple[str, str]:
    """
    Extract the body from an email message.
    Returns: (body_content, content_type) where content_type is 'html' or 'plain'
    """
    html_body = None
    plain_body = None
    
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition"))
            if "attachment" in disp:
                continue
                
            if ctype == "text/html":
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload is not None:
                    html_body = payload.decode(charset, errors="ignore")
            elif ctype == "text/plain" and plain_body is None:
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload is not None:
                    plain_body = payload.decode(charset, errors="ignore")
    else:
        ctype = msg.get_content_type()
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            decoded = payload.decode(charset, errors="ignore")
            if ctype == "text/html":
                html_body = decoded
            else:
                plain_body = decoded
    
    # Prefer HTML over plain text
    if html_body:
        return html_body, "html"
    elif plain_body:
        return plain_body, "plain"
    
    return "", "unknown"


def get_stable_message_id(msg: email.message.Message, imap_seq: str) -> str:
    """
    Get a stable identifier for an email message.
    Prefers Message-ID header, falls back to a combination of Subject + Date,
    and finally to IMAP sequence number.
    """
    # Try Message-ID header first (most stable)
    msg_id_header = msg.get("Message-ID", "").strip()
    if msg_id_header:
        return msg_id_header
    
    # Fall back to Subject + Date combination
    subject = decode_header_value(msg.get("Subject", ""))
    date = msg.get("Date", "")
    if subject and date:
        combined = f"{subject}|{date}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    # Last resort: use IMAP sequence number
    return f"imap_seq_{imap_seq}"


def parse_ao3_email(body: str, content_type: str, email_subject: str) -> Optional[Dict]:
    """
    Parse AO3 work info from email body (HTML or plain text).
    """
    # Try to extract work ID and URL from the body
    # Look for /works/ pattern in both HTML and plain text
    work_id_match = re.search(r"/works/(\d+)", body)
    if not work_id_match:
        return None
    
    ao3_id = work_id_match.group(1)
    
    # Construct URL - just use the work ID, nothing after it
    url = f"https://archiveofourown.org/works/{ao3_id}"
    
    # Parse title - try HTML first, then plain text
    # Also prepare text for word count extraction
    title = None
    soup = None
    text = None
    
    if content_type == "html":
        soup = BeautifulSoup(body, "lxml")
        # Look for work link text
        for a in soup.find_all("a", href=True):
            if "/works/" in a["href"]:
                title_text = a.get_text(strip=True)
                if title_text and title_text != url:
                    title = title_text
                    break
        
        # If no title from link, try to find it in the text
        if not title:
            # Look for common patterns in AO3 emails
            text = soup.get_text(" ", strip=True)
            # Try to find title after common phrases
            title_match = re.search(r"(?:posted|updated)\s+(?:Chapter\s+\d+\s+of\s+)?(.+?)(?:\s+has been|$)", text, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).strip()
        
        # Extract author from HTML
        author = None
        for a in soup.find_all("a", href=True):
            if "/users/" in a["href"] or "/pseuds/" in a["href"]:
                author = a.get_text(strip=True)
                if author:
                    break
        
        # Get text for word count extraction if not already done
        if text is None:
            text = soup.get_text(" ", strip=True)
    else:
        # Plain text parsing
        # Try to extract title from subject or body
        # Subject format: "[AO3] Author posted Chapter X of Title"
        title_match = re.search(r"(?:posted|updated)\s+(?:Chapter\s+\d+\s+of\s+)?(.+?)(?:\s+has been|$)", email_subject, re.IGNORECASE)
        if not title_match:
            # Try from body text
            title_match = re.search(r"(?:posted|updated)\s+(?:Chapter\s+\d+\s+of\s+)?(.+?)(?:\s+has been|$)", body, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
        
        # Extract author from subject or body
        author = None
        # Subject format: "[AO3] AuthorName posted..."
        author_match = re.search(r"\[AO3\]\s*([^\s]+)\s+(?:posted|updated)", email_subject, re.IGNORECASE)
        if author_match:
            author = author_match.group(1)
        else:
            # Try from body
            author_match = re.search(r"by\s+([^\s]+)", body, re.IGNORECASE)
            if author_match:
                author = author_match.group(1)
        
        # Get text for word count extraction
        text = body
    
    if not title:
        title = "(untitled work)"
    
    # Chapter info
    chapter_label = "Update"
    m = re.search(r"Chapter\s+(\d+)", email_subject, re.IGNORECASE)
    if m:
        chapter_label = f"Chapter {m.group(1)}"
    else:
        search_text = text if text else body
        m2 = re.search(r"Chapter\s+(\d+)", search_text, re.IGNORECASE)
        if m2:
            chapter_label = f"Chapter {m2.group(1)}"
        else:
            subj_lower = email_subject.lower()
            if "has been updated" in subj_lower:
                chapter_label = "Updated"
            elif "has been posted" in subj_lower or "posted" in subj_lower:
                # Check if it's a new work or series update
                if "series" in subj_lower:
                    chapter_label = "Series Update"
                else:
                    chapter_label = "New Work"
            elif "Quirk Analysis" in email_subject or "Analysis" in email_subject:
                chapter_label = "Analysis"
            elif "Final Bows" in email_subject:
                chapter_label = "Complete"

    # Extract word counts
    chapter_word_count = None
    work_word_count = None
    
    # Use the text we already prepared (or body for plain text)
    if text is None:
        text = body
    
    # First, look for the pattern at the top of the email:
    # "xyz posted a new chapter of abc ( 12345 words):" or
    # "xyz posted Chapter X of abc ( 12345 words):"
    # This is usually the work total word count
    top_patterns = [
        r"posted\s+(?:a\s+new\s+chapter\s+of|Chapter\s+\d+\s+of)\s+[^(]*\([\s]*([\d,]+)\s+words?\)",  # "posted Chapter X of title ( 12345 words)"
        r"posted\s+[^(]*\([\s]*([\d,]+)\s+words?\)",  # "posted title ( 12345 words)"
        r"posted\s+(?:a\s+new\s+chapter\s+of|Chapter\s+\d+\s+of)\s+[^:]*:[\s]*([\d,]+)\s+words?",  # "posted Chapter X of title: 12345 words"
    ]
    
    # Look in the first 500 characters (top of email) for this pattern
    top_text = text[:500] if len(text) > 500 else text
    for pattern in top_patterns:
        match = re.search(pattern, top_text, re.IGNORECASE)
        if match:
            try:
                work_word_count = int(match.group(1).replace(",", "").strip())
                break
            except (ValueError, IndexError):
                continue
    
    # Look for word count patterns throughout the email
    # Chapter word count patterns
    chapter_word_patterns = [
        r"Chapter\s+\d+\s*[\(:]?\s*([\d,]+)\s+words?",  # "Chapter 5 (1,234 words)"
        r"([\d,]+)\s+words?\s+in\s+this\s+chapter",  # "1,234 words in this chapter"
        r"([\d,]+)\s+words?\s+\(chapter",  # "1,234 words (chapter"
    ]
    
    # Additional work total word count patterns
    work_word_patterns = [
        r"total[:\s]+([\d,]+)\s+words?",  # "Total: 50,000 words"
        r"work\s+total[:\s]+([\d,]+)\s+words?",  # "Work total: 50,000 words"
        r"([\d,]+)\s+words?\s+total",  # "50,000 words total"
        r"([\d,]+)\s+words?\s+\(work",  # "50,000 words (work"
    ]
    
    # Try to find chapter word count
    for pattern in chapter_word_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                chapter_word_count = int(match.group(1).replace(",", ""))
                break
            except (ValueError, IndexError):
                continue
    
    # Try to find work total word count (if not already found from top pattern)
    if work_word_count is None:
        for pattern in work_word_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    work_word_count = int(match.group(1).replace(",", ""))
                    break
                except (ValueError, IndexError):
                    continue
    
    # If we didn't find specific patterns, look for general word count mentions
    # and try to infer which is chapter vs work
    if chapter_word_count is None and work_word_count is None:
        # Look for all "X words" patterns
        all_word_matches = re.findall(r"([\d,]+)\s+words?", text, re.IGNORECASE)
        if len(all_word_matches) >= 2:
            # Usually the smaller number is chapter, larger is work total
            try:
                word_counts = [int(w.replace(",", "")) for w in all_word_matches]
                word_counts.sort()
                chapter_word_count = word_counts[0] if len(word_counts) > 0 else None
                work_word_count = word_counts[-1] if len(word_counts) > 1 else None
            except ValueError:
                pass
        elif len(all_word_matches) == 1:
            # Only one word count found - could be either
            try:
                count = int(all_word_matches[0].replace(",", ""))
                # If it's a large number (>10k), likely work total
                if count > 10000:
                    work_word_count = count
                else:
                    chapter_word_count = count
            except ValueError:
                pass

    return {
        "ao3_id": ao3_id,
        "title": title,
        "author": author,
        "url": url,
        "chapter_label": chapter_label,
        "chapter_word_count": chapter_word_count,
        "work_word_count": work_word_count,
    }


def ingest_new_ao3_emails_imap(max_messages: Optional[int] = 100):
    init_db()
    conn = get_connection()
    
    # Log the start of ingestion
    log_id = log_ingestion_start(conn)
    error_message = None

    mail = connect_imap()
    try:
        mailbox = select_ao3_mailbox(mail)
        print(f"Selected mailbox: {mailbox}")

        msg_ids = fetch_message_ids(mail, mailbox, limit=max_messages)
        print(f"Found {len(msg_ids)} candidate AO3 messages.")

        processed_count = 0
        skipped_count = 0

        for msg_id in msg_ids:
            imap_seq = msg_id.decode("ascii", errors="ignore")
            
            raw = fetch_raw_message(mail, msg_id)
            msg = email.message_from_bytes(raw)

            # Get a stable message identifier (prefer Message-ID header)
            stable_msg_id = get_stable_message_id(msg, imap_seq)
            
            if has_processed_message(conn, stable_msg_id):
                skipped_count += 1
                continue

            subject = decode_header_value(msg.get("Subject"))
            date_raw = msg.get("Date", "")
            # Parse the email date into ISO format for better time-based queries
            if date_raw:
                try:
                    from email.utils import parsedate_to_datetime
                    date_obj = parsedate_to_datetime(date_raw)
                    date = date_obj.isoformat()  # Store as ISO 8601 format
                except (ValueError, TypeError):
                    # Fallback to raw date if parsing fails
                    date = date_raw
            else:
                date = ""

            body, content_type = extract_body_from_email(msg)
            if not body:
                print(f"[WARN] No body found for message {imap_seq} (ID: {stable_msg_id})")
                mark_processed_message(conn, stable_msg_id)
                continue

            parsed = parse_ao3_email(body, content_type, subject)
            if not parsed:
                print(f"[WARN] Could not parse AO3 info from message {imap_seq} (subject: {subject!r}, type: {content_type})")
                mark_processed_message(conn, stable_msg_id)
                continue

            work = {
                "ao3_id": parsed["ao3_id"],
                "title": parsed["title"],
                "author": parsed["author"],
                "url": parsed["url"],
            }

            upsert_work_and_add_update(
                conn=conn,
                work=work,
                chapter_label=parsed["chapter_label"],
                email_subject=subject,
                email_date=date,
                chapter_word_count=parsed.get("chapter_word_count"),
                work_word_count=parsed.get("work_word_count"),
            )
            mark_processed_message(conn, stable_msg_id)
            processed_count += 1
            print(f"[OK] {work['title']} – {parsed['chapter_label']} ({subject})")

        print(f"Done. Processed {processed_count} new messages, skipped {skipped_count} already-seen.")

    except Exception as e:
        error_message = str(e)
        print(f"Error during ingestion: {error_message}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            mail.logout()
        except:
            pass
        # Log the completion of ingestion
        log_ingestion_complete(
            conn,
            log_id,
            messages_processed=processed_count,
            messages_skipped=skipped_count,
            error_message=error_message,
        )
        conn.close()


if __name__ == "__main__":
    import sys
    
    # Allow command-line argument to specify max messages, or None for all
    if len(sys.argv) > 1:
        if sys.argv[1].lower() in ("all", "none", "-1"):
            max_messages = None
            print("Processing ALL messages...")
        else:
            try:
                max_messages = int(sys.argv[1])
                print(f"Processing up to {max_messages} messages...")
            except ValueError:
                print(f"Invalid argument: {sys.argv[1]}. Use a number or 'all'")
                sys.exit(1)
    else:
        max_messages = 100
        print("Processing up to 100 messages (default). Use 'all' or a number to process more.")
    
    ingest_new_ao3_emails_imap(max_messages=max_messages)
