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
    
    # Add new metadata columns for scraping integration
    new_columns = [
        ('fandoms', 'TEXT'),
        ('rating', 'TEXT'),
        ('archive_warnings', 'TEXT'),
        ('categories', 'TEXT'),
        ('relationships', 'TEXT'),
        ('characters', 'TEXT'),
        ('additional_tags', 'TEXT'),
        ('language', 'TEXT'),
        ('chapters_current', 'INTEGER'),
        ('chapters_max', 'INTEGER'),
        ('status', 'TEXT'),
        ('published_at', 'TEXT'),
        ('updated_at', 'TEXT'),
        ('summary_html', 'TEXT'),
        ('metadata_source', 'TEXT'),
    ]
    
    for column_name, column_type in new_columns:
        cur.execute("""
            SELECT COUNT(*) FROM pragma_table_info('works') WHERE name=?
        """, (column_name,))
        if cur.fetchone()[0] == 0:
            cur.execute(f"ALTER TABLE works ADD COLUMN {column_name} {column_type}")
    
    # Set default metadata_source for existing rows
    cur.execute("""
        UPDATE works SET metadata_source = 'email' WHERE metadata_source IS NULL
    """)

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
    
    # Add is_read column if it doesn't exist (for existing databases)
    cur.execute("""
        SELECT COUNT(*) FROM pragma_table_info('updates') WHERE name='is_read'
    """)
    if cur.fetchone()[0] == 0:
        cur.execute("ALTER TABLE updates ADD COLUMN is_read INTEGER DEFAULT 0")

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


def mark_updates_as_read(conn: sqlite3.Connection, work_id: int):
    """Mark all updates for a work as read."""
    cur = conn.cursor()
    cur.execute("UPDATE updates SET is_read = 1 WHERE work_id = ?", (work_id,))
    conn.commit()


def mark_update_as_read(conn: sqlite3.Connection, update_id: int):
    """Mark a specific update as read."""
    cur = conn.cursor()
    cur.execute("UPDATE updates SET is_read = 1 WHERE id = ?", (update_id,))
    conn.commit()


def upsert_work_with_metadata(
    conn: sqlite3.Connection,
    work_metadata: Dict[str, Any],
) -> int:
    """
    Insert or update a work with full metadata from scraping.
    
    Args:
        conn: Database connection
        work_metadata: Dict with keys matching database columns:
            - ao3_id (required)
            - title, author, url
            - fandoms, rating, archive_warnings, categories, relationships, characters, additional_tags
            - language, chapters_current, chapters_max, status
            - published_at, updated_at, summary_html
            - total_word_count
            - metadata_source ('email', 'scrape', 'mixed')
    
    Returns:
        work_id: The ID of the inserted or updated work
    """
    cur = conn.cursor()
    
    ao3_id = work_metadata.get("ao3_id")
    if not ao3_id:
        raise ValueError("ao3_id is required")
    
    # Check if work exists
    cur.execute("SELECT id, metadata_source FROM works WHERE ao3_id = ?", (ao3_id,))
    existing = cur.fetchone()
    
    from datetime import datetime
    now_str = datetime.utcnow().isoformat()
    
    # Determine metadata_source
    if existing:
        existing_source = existing["metadata_source"] or "email"
        if existing_source == "email":
            metadata_source = "mixed"
        else:
            metadata_source = existing_source
    else:
        metadata_source = work_metadata.get("metadata_source", "scrape")
    
    # Prepare values with COALESCE to preserve existing data when new data is None
    if existing:
        work_id = existing["id"]
        # Update existing work, using COALESCE to preserve existing values
        cur.execute("""
            UPDATE works SET
                title = COALESCE(?, title),
                author = COALESCE(?, author),
                url = COALESCE(?, url),
                total_word_count = COALESCE(?, total_word_count),
                fandoms = COALESCE(?, fandoms),
                rating = COALESCE(?, rating),
                archive_warnings = COALESCE(?, archive_warnings),
                categories = COALESCE(?, categories),
                relationships = COALESCE(?, relationships),
                characters = COALESCE(?, characters),
                additional_tags = COALESCE(?, additional_tags),
                language = COALESCE(?, language),
                chapters_current = COALESCE(?, chapters_current),
                chapters_max = COALESCE(?, chapters_max),
                status = COALESCE(?, status),
                published_at = COALESCE(?, published_at),
                updated_at = COALESCE(?, updated_at),
                summary_html = COALESCE(?, summary_html),
                metadata_source = ?,
                last_update_at = ?
            WHERE id = ?
        """, (
            work_metadata.get("title"),
            work_metadata.get("author"),
            work_metadata.get("url"),
            work_metadata.get("total_word_count"),
            work_metadata.get("fandoms"),
            work_metadata.get("rating"),
            work_metadata.get("archive_warnings"),
            work_metadata.get("categories"),
            work_metadata.get("relationships"),
            work_metadata.get("characters"),
            work_metadata.get("additional_tags"),
            work_metadata.get("language"),
            work_metadata.get("chapters_current"),
            work_metadata.get("chapters_max"),
            work_metadata.get("status"),
            work_metadata.get("published_at"),
            work_metadata.get("updated_at"),
            work_metadata.get("summary_html"),
            metadata_source,
            now_str,
            work_id,
        ))
    else:
        # Insert new work
        cur.execute("""
            INSERT INTO works (
                ao3_id, title, author, url, total_word_count,
                fandoms, rating, archive_warnings, categories, relationships,
                characters, additional_tags, language, chapters_current, chapters_max,
                status, published_at, updated_at, summary_html, metadata_source,
                last_update_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ao3_id,
            work_metadata.get("title"),
            work_metadata.get("author"),
            work_metadata.get("url"),
            work_metadata.get("total_word_count"),
            work_metadata.get("fandoms"),
            work_metadata.get("rating"),
            work_metadata.get("archive_warnings"),
            work_metadata.get("categories"),
            work_metadata.get("relationships"),
            work_metadata.get("characters"),
            work_metadata.get("additional_tags"),
            work_metadata.get("language"),
            work_metadata.get("chapters_current"),
            work_metadata.get("chapters_max"),
            work_metadata.get("status"),
            work_metadata.get("published_at"),
            work_metadata.get("updated_at"),
            work_metadata.get("summary_html"),
            metadata_source,
            now_str,
        ))
        work_id = cur.lastrowid
    
    conn.commit()
    return work_id
