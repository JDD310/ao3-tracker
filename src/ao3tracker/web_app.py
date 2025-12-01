from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ao3tracker.db import get_connection, mark_updates_as_read
from ao3tracker.models import (
    Update,
    UpdateWithWork,
    UpdatesResponse,
    Work,
    WorkDetail,
    WorksResponse,
)


def parse_email_date(date_str: str) -> Optional[datetime]:
    """Parse email date string, handling ISO format and other common formats."""
    if not date_str:
        return None
    
    try:
        # Try ISO format first (most common)
        date_str_clean = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(date_str_clean)
    except (ValueError, AttributeError):
        try:
            # Try parsing with email.utils
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str)
        except (ValueError, TypeError, AttributeError):
            return None

# Get project root (same level as src/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Set up template and static directories
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Create FastAPI app instance
app = FastAPI()

# Set up Jinja2 templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Mount static files at /static
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def list_updates(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    author: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    unread_only: bool = Query(False),
):
    """
    Show the most recent updates across all works with pagination and filtering.
    """
    conn = get_connection()
    cur = conn.cursor()
    
    # Build WHERE clause
    conditions = []
    params = []
    
    if author:
        conditions.append("w.author LIKE ?")
        params.append(f"%{author}%")
    
    if date_from:
        conditions.append("u.email_date >= ?")
        params.append(date_from)
    
    if date_to:
        conditions.append("u.email_date <= ?")
        params.append(date_to)
    
    if unread_only:
        conditions.append("(u.is_read = 0 OR u.is_read IS NULL)")
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    # Get total count
    count_query = f"""
        SELECT COUNT(*)
        FROM updates u
        JOIN works w ON u.work_id = w.id
        WHERE {where_clause}
    """
    total = cur.execute(count_query, params).fetchone()[0]
    
    # Get paginated results
    offset = (page - 1) * page_size
    query = f"""
        SELECT
            u.id AS update_id,
            w.id AS work_id,
            w.title,
            w.author,
            w.url,
            u.chapter_label,
            u.email_subject,
            u.email_date,
            u.created_at,
            u.is_read
        FROM updates u
        JOIN works w ON u.work_id = w.id
        WHERE {where_clause}
        ORDER BY u.email_date DESC
        LIMIT ? OFFSET ?
    """
    params.extend([page_size, offset])
    rows = cur.execute(query, params).fetchall()
    updates = [dict(row) for row in rows]
    
    total_pages = (total + page_size - 1) // page_size
    
    conn.close()
    return templates.TemplateResponse(
        "updates.html",
        {
            "request": request,
            "updates": updates,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "author": author or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
            "unread_only": unread_only,
        },
    )


@app.get("/works", response_class=HTMLResponse)
async def list_works(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    author: Optional[str] = None,
):
    conn = get_connection()
    cur = conn.cursor()
    
    conditions = []
    params = []
    
    if author:
        conditions.append("author LIKE ?")
        params.append(f"%{author}%")
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    # Get total count
    count_query = f"SELECT COUNT(*) FROM works WHERE {where_clause}"
    total = cur.execute(count_query, params).fetchone()[0]
    
    # Get paginated results
    offset = (page - 1) * page_size
    query = f"""
        SELECT
            id,
            ao3_id,
            title,
            author,
            url,
            last_seen_chapter,
            last_update_at
        FROM works
        WHERE {where_clause}
        ORDER BY title ASC
        LIMIT ? OFFSET ?
    """
    params.extend([page_size, offset])
    rows = cur.execute(query, params).fetchall()
    works = [dict(row) for row in rows]
    
    total_pages = (total + page_size - 1) // page_size
    
    conn.close()
    return templates.TemplateResponse(
        "works.html",
        {
            "request": request,
            "works": works,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "author": author or "",
        },
    )


@app.get("/works/{work_id}", response_class=HTMLResponse)
async def work_detail(work_id: int, request: Request):
    conn = get_connection()
    cur = conn.cursor()

    work_row = cur.execute("""
        SELECT
            id,
            ao3_id,
            title,
            author,
            url,
            last_seen_chapter,
            last_update_at,
            total_word_count
        FROM works
        WHERE id = ?
    """, (work_id,)).fetchone()

    if work_row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Work not found")

    work = dict(work_row)

    updates_rows = cur.execute("""
        SELECT
            id,
            chapter_label,
            email_subject,
            email_date,
            created_at,
            chapter_word_count,
            work_word_count,
            is_read
        FROM updates
        WHERE work_id = ?
        ORDER BY email_date ASC
    """, (work_id,)).fetchall()

    updates = [dict(u) for u in updates_rows]
    
    # Calculate statistics
    stats = calculate_work_statistics(updates, work)
    
    # Count unread updates
    unread_count = sum(1 for u in updates if not u.get("is_read", 0))
    
    conn.close()
    return templates.TemplateResponse(
        "work_detail.html",
        {
            "request": request,
            "work": work,
            "updates": updates,
            "stats": stats,
            "unread_count": unread_count,
        },
    )


@app.post("/works/{work_id}/mark-read", response_class=HTMLResponse)
async def mark_work_read(work_id: int, request: Request):
    """Mark all updates for a work as read."""
    conn = get_connection()
    cur = conn.cursor()
    
    # Verify work exists
    work_row = cur.execute("SELECT id FROM works WHERE id = ?", (work_id,)).fetchone()
    if work_row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Work not found")
    
    mark_updates_as_read(conn, work_id)
    conn.close()
    
    # Redirect back to work detail page
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/works/{work_id}", status_code=303)


def calculate_work_statistics(updates: list, work: dict) -> dict:
    """Calculate statistics about a work based on its updates."""
    stats = {
        "total_updates": len(updates),
        "average_words_per_chapter": None,
        "total_word_count": work.get("total_word_count"),
        "next_expected_release": None,
        "average_days_between_updates": None,
        "word_count_data": [],
    }
    
    if not updates:
        return stats
    
    # Collect word count data for graph (work_word_count over time)
    word_count_data = []
    chapter_word_counts = []
    
    for update in updates:
        if update.get("work_word_count") is not None:
            try:
                # Parse email_date (ISO format)
                email_date = update["email_date"]
                if email_date:
                    word_count_data.append({
                        "date": email_date,
                        "word_count": update["work_word_count"]
                    })
            except (ValueError, TypeError):
                pass
        
        if update.get("chapter_word_count") is not None:
            chapter_word_counts.append(update["chapter_word_count"])
    
    stats["word_count_data"] = word_count_data
    
    # Calculate average words per chapter
    if chapter_word_counts:
        stats["average_words_per_chapter"] = sum(chapter_word_counts) / len(chapter_word_counts)
    
    # Calculate average days between updates and predict next release
    if len(updates) >= 2:
        date_diffs = []
        valid_dates = []
        
        for i in range(1, len(updates)):
            date1_str = updates[i-1]["email_date"]
            date2_str = updates[i]["email_date"]
            
            date1 = parse_email_date(date1_str) if date1_str else None
            date2 = parse_email_date(date2_str) if date2_str else None
            
            if date1 and date2:
                diff = (date2 - date1).days
                if diff > 0:  # Only count positive differences
                    date_diffs.append(diff)
                    valid_dates.append((date1, date2))
        
        if date_diffs:
            avg_days = sum(date_diffs) / len(date_diffs)
            stats["average_days_between_updates"] = round(avg_days, 1)
            
            # Predict next release date based on last update + average days
            if valid_dates:
                last_date = valid_dates[-1][1]
                next_release = last_date + timedelta(days=avg_days)
                stats["next_expected_release"] = next_release.isoformat()
    
    return stats


# ============================================================================
# API Routes
# ============================================================================

@app.get("/api/v1/updates", response_model=UpdatesResponse)
async def api_list_updates(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    author: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    unread_only: bool = False,
):
    """List updates with pagination and filtering."""
    conn = get_connection()
    cur = conn.cursor()
    
    # Build WHERE clause
    conditions = []
    params = []
    
    if author:
        conditions.append("w.author LIKE ?")
        params.append(f"%{author}%")
    
    if date_from:
        conditions.append("u.email_date >= ?")
        params.append(date_from)
    
    if date_to:
        conditions.append("u.email_date <= ?")
        params.append(date_to)
    
    if unread_only:
        conditions.append("(u.is_read = 0 OR u.is_read IS NULL)")
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    # Get total count
    count_query = f"""
        SELECT COUNT(*)
        FROM updates u
        JOIN works w ON u.work_id = w.id
        WHERE {where_clause}
    """
    total = cur.execute(count_query, params).fetchone()[0]
    
    # Get paginated results
    offset = (page - 1) * page_size
    query = f"""
        SELECT
            u.id,
            u.work_id,
            u.chapter_label,
            u.email_subject,
            u.email_date,
            u.chapter_word_count,
            u.work_word_count,
            u.created_at,
            u.is_read,
            w.title AS work_title,
            w.author AS work_author,
            w.url AS work_url
        FROM updates u
        JOIN works w ON u.work_id = w.id
        WHERE {where_clause}
        ORDER BY u.email_date DESC
        LIMIT ? OFFSET ?
    """
    params.extend([page_size, offset])
    rows = cur.execute(query, params).fetchall()
    
    updates = []
    for row in rows:
        update_dict = dict(row)
        update_dict["is_read"] = bool(update_dict.get("is_read", 0))
        updates.append(UpdateWithWork(**update_dict))
    
    conn.close()
    
    total_pages = (total + page_size - 1) // page_size
    
    return UpdatesResponse(
        items=updates,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@app.get("/api/v1/works", response_model=WorksResponse)
async def api_list_works(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    author: Optional[str] = None,
):
    """List works with pagination and filtering."""
    conn = get_connection()
    cur = conn.cursor()
    
    conditions = []
    params = []
    
    if author:
        conditions.append("author LIKE ?")
        params.append(f"%{author}%")
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    # Get total count
    count_query = f"SELECT COUNT(*) FROM works WHERE {where_clause}"
    total = cur.execute(count_query, params).fetchone()[0]
    
    # Get paginated results
    offset = (page - 1) * page_size
    query = f"""
        SELECT id, ao3_id, title, author, url, last_seen_chapter, last_update_at, total_word_count
        FROM works
        WHERE {where_clause}
        ORDER BY title ASC
        LIMIT ? OFFSET ?
    """
    params.extend([page_size, offset])
    rows = cur.execute(query, params).fetchall()
    
    works = [Work(**dict(row)) for row in rows]
    conn.close()
    
    total_pages = (total + page_size - 1) // page_size
    
    return WorksResponse(
        items=works,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@app.get("/api/v1/works/{work_id}", response_model=WorkDetail)
async def api_work_detail(work_id: int):
    """Get work details with updates."""
    conn = get_connection()
    cur = conn.cursor()
    
    work_row = cur.execute("""
        SELECT id, ao3_id, title, author, url, last_seen_chapter, last_update_at, total_word_count
        FROM works
        WHERE id = ?
    """, (work_id,)).fetchone()
    
    if work_row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Work not found")
    
    work = Work(**dict(work_row))
    
    updates_rows = cur.execute("""
        SELECT id, work_id, chapter_label, email_subject, email_date, created_at,
               chapter_word_count, work_word_count, is_read
        FROM updates
        WHERE work_id = ?
        ORDER BY email_date ASC
    """, (work_id,)).fetchall()
    
    updates = []
    for row in updates_rows:
        update_dict = dict(row)
        update_dict["is_read"] = bool(update_dict.get("is_read", 0))
        updates.append(Update(**update_dict))
    
    conn.close()
    
    work_detail = WorkDetail(**work.model_dump(), updates=updates)
    return work_detail


@app.post("/api/v1/works/{work_id}/mark-read")
async def api_mark_work_read(work_id: int):
    """Mark all updates for a work as read."""
    conn = get_connection()
    cur = conn.cursor()
    
    # Verify work exists
    work_row = cur.execute("SELECT id FROM works WHERE id = ?", (work_id,)).fetchone()
    if work_row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Work not found")
    
    mark_updates_as_read(conn, work_id)
    conn.close()
    
    return {"status": "success", "message": f"All updates for work {work_id} marked as read"}


# ============================================================================
# HTML Routes (updated with pagination and filtering)
# ============================================================================

@app.get("/search", response_class=HTMLResponse)
async def search_works(
    request: Request,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """Search works by title or author."""
    conn = get_connection()
    cur = conn.cursor()
    
    works = []
    total = 0
    total_pages = 0
    
    if q:
        # Use LIKE for search (FTS5 can be added later)
        query = """
            SELECT id, ao3_id, title, author, url, last_seen_chapter, last_update_at, total_word_count
            FROM works
            WHERE title LIKE ? OR author LIKE ?
            ORDER BY title ASC
            LIMIT ? OFFSET ?
        """
        search_term = f"%{q}%"
        offset = (page - 1) * page_size
        
        # Get total count
        count_query = "SELECT COUNT(*) FROM works WHERE title LIKE ? OR author LIKE ?"
        total = cur.execute(count_query, (search_term, search_term)).fetchone()[0]
        
        # Get paginated results
        rows = cur.execute(query, (search_term, search_term, page_size, offset)).fetchall()
        works = [dict(row) for row in rows]
        
        total_pages = (total + page_size - 1) // page_size
    
    conn.close()
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "works": works,
            "query": q or "",
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    )


@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    """Show system status and statistics."""
    conn = get_connection()
    cur = conn.cursor()
    
    # Get counts
    works_count = cur.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    updates_count = cur.execute("SELECT COUNT(*) FROM updates").fetchone()[0]
    unread_count = cur.execute("SELECT COUNT(*) FROM updates WHERE is_read = 0 OR is_read IS NULL").fetchone()[0]
    
    # Get last update time
    last_update_row = cur.execute("""
        SELECT MAX(email_date) FROM updates
    """).fetchone()
    last_update_time = last_update_row[0] if last_update_row and last_update_row[0] else None
    
    # Get last ingestion time (from processed_messages or updates created_at)
    last_ingestion_row = cur.execute("""
        SELECT MAX(created_at) FROM updates
    """).fetchone()
    last_ingestion_time = last_ingestion_row[0] if last_ingestion_row and last_ingestion_row[0] else None
    
    conn.close()
    
    return templates.TemplateResponse(
        "status.html",
        {
            "request": request,
            "works_count": works_count,
            "updates_count": updates_count,
            "unread_count": unread_count,
            "last_update_time": last_update_time,
            "last_ingestion_time": last_ingestion_time,
        },
    )


@app.get("/health", response_class=PlainTextResponse)
async def health():
    """Health check endpoint."""
    return "OK"

