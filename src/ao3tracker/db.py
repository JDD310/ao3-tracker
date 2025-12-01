from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any

DB_PATH = Path("ao3_tracker.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS works (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ao3_id TEXT UNIQUE,
            title TEXT,
            author TEXT,
            url TEXT,
            last_seen_chapter TEXT,
            last_update_at TEXT,
            total_word_count INTEGER
        )
    """)
    
    # Add total_word_count column if it doesn't exist (for existing databases)
    cur.execute("""
        SELECT COUNT(*) FROM pragma_table_info('works') WHERE name='total_word_count'
    """)
    if cur.fetchone()[0] == 0:
        cur.execute("ALTER TABLE works ADD COLUMN total_word_count INTEGER")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_id INTEGER,
            chapter_label TEXT,
            email_subject TEXT,
            email_date TEXT,
            chapter_word_count INTEGER,
            work_word_count INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (work_id) REFERENCES works (id)
        )
    """)
    
    # Add word count columns if they don't exist (for existing databases)
    cur.execute("""
        SELECT COUNT(*) FROM pragma_table_info('updates') WHERE name='chapter_word_count'
    """)
    if cur.fetchone()[0] == 0:
        cur.execute("ALTER TABLE updates ADD COLUMN chapter_word_count INTEGER")
    
    cur.execute("""
        SELECT COUNT(*) FROM pragma_table_info('updates') WHERE name='work_word_count'
    """)
    if cur.fetchone()[0] == 0:
        cur.execute("ALTER TABLE updates ADD COLUMN work_word_count INTEGER")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS processed_messages (
            message_id TEXT PRIMARY KEY
        )
    """)

    conn.commit()
    conn.close()


def has_processed_message(conn: sqlite3.Connection, message_id: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM processed_messages WHERE message_id = ?", (message_id,))
    return cur.fetchone() is not None


def mark_processed_message(conn: sqlite3.Connection, message_id: str):
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO processed_messages (message_id) VALUES (?)", (message_id,))
    conn.commit()


def upsert_work_and_add_update(
    conn: sqlite3.Connection,
    work: Dict[str, Any],
    chapter_label: str,
    email_subject: str,
    email_date: str,
    chapter_word_count: Optional[int] = None,
    work_word_count: Optional[int] = None,
):
    """
    work: {
        "ao3_id": str,
        "title": str,
        "author": str,
        "url": str,
    }
    """
    cur = conn.cursor()

    cur.execute("SELECT id FROM works WHERE ao3_id = ?", (work["ao3_id"],))
    row = cur.fetchone()

    from datetime import datetime
    now_str = datetime.utcnow().isoformat()

    # Use work_word_count as the total if available, otherwise keep existing
    total_word_count = work_word_count

    if row is None:
        cur.execute("""
            INSERT INTO works (ao3_id, title, author, url, last_seen_chapter, last_update_at, total_word_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            work["ao3_id"],
            work["title"],
            work["author"],
            work["url"],
            chapter_label,
            now_str,
            total_word_count,
        ))
        work_id = cur.lastrowid
    else:
        work_id = row["id"]
        # Only update total_word_count if we have a new value
        if total_word_count is not None:
            cur.execute("""
                UPDATE works
                SET title = ?, author = ?, url = ?, last_seen_chapter = ?, last_update_at = ?, total_word_count = ?
                WHERE id = ?
            """, (
                work["title"],
                work["author"],
                work["url"],
                chapter_label,
                now_str,
                total_word_count,
                work_id,
            ))
        else:
            cur.execute("""
                UPDATE works
                SET title = ?, author = ?, url = ?, last_seen_chapter = ?, last_update_at = ?
                WHERE id = ?
            """, (
                work["title"],
                work["author"],
                work["url"],
                chapter_label,
                now_str,
                work_id,
            ))

    cur.execute("""
        INSERT INTO updates (work_id, chapter_label, email_subject, email_date, chapter_word_count, work_word_count)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        work_id,
        chapter_label,
        email_subject,
        email_date,
        chapter_word_count,
        work_word_count,
    ))

    conn.commit()


def clear_processed_messages(conn: sqlite3.Connection):
    """Clear all processed message records."""
    cur = conn.cursor()
    cur.execute("DELETE FROM processed_messages")
    conn.commit()


def reset_database():
    """
    Reset the entire database by dropping all tables and recreating them.
    WARNING: This will delete all data!
    """
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("DROP TABLE IF EXISTS updates")
    cur.execute("DROP TABLE IF EXISTS works")
    cur.execute("DROP TABLE IF EXISTS processed_messages")
    
    conn.commit()
    conn.close()
    
    # Recreate tables
    init_db()
    print("Database reset complete. All tables recreated.")


def reset_processed_messages_only():
    """Reset only the processed_messages table, keeping works and updates."""
    conn = get_connection()
    clear_processed_messages(conn)
    conn.close()
    print("Processed messages table cleared. Works and updates remain intact.")
