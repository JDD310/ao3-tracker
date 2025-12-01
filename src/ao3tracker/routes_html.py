from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ao3tracker.db import get_connection, mark_updates_as_read
from ao3tracker.utils import calculate_work_statistics
from ao3tracker.scrape_works import scrape_and_store_works

# Get project root (same level as src/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Set up template directory
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["html"])


@router.get("/", response_class=HTMLResponse)
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
    
    # Get last ingestion time
    from ao3tracker.db import get_last_ingestion_time
    last_ingestion_time = get_last_ingestion_time(conn)
    
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
            "last_ingestion_time": last_ingestion_time,
        },
    )


@router.get("/works", response_class=HTMLResponse)
async def list_works(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    author: Optional[str] = None,
    filter: Optional[str] = Query(None, description="Filter: 'updated' for works with updates, 'all' for all works"),
    sort: Optional[str] = Query("title", description="Sort by: 'title', 'word_count', 'next_release'"),
):
    from ao3tracker.utils import calculate_work_statistics
    
    conn = get_connection()
    cur = conn.cursor()
    
    conditions = []
    params = []
    
    if author:
        conditions.append("w.author LIKE ?")
        params.append(f"%{author}%")
    
    # Add filter for updated works
    if filter == "updated":
        conditions.append("EXISTS (SELECT 1 FROM updates u WHERE u.work_id = w.id)")
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    # Get total count
    count_query = f"SELECT COUNT(*) FROM works w WHERE {where_clause}"
    total = cur.execute(count_query, params).fetchone()[0]
    
    # Get all works with word count and most recent chapter label
    # We'll fetch all matching works, calculate next_expected_release, sort, then paginate
    query = f"""
        SELECT
            w.id,
            w.ao3_id,
            w.title,
            w.author,
            w.url,
            w.last_update_at,
            w.total_word_count,
            w.updated_at,
            w.published_at,
            w.chapters_current,
            w.chapters_max,
            (SELECT u.chapter_label 
             FROM updates u 
             WHERE u.work_id = w.id 
             ORDER BY u.email_date DESC, u.id DESC 
             LIMIT 1) AS last_seen_chapter
        FROM works w
        WHERE {where_clause}
    """
    rows = cur.execute(query, params).fetchall()
    all_works = [dict(row) for row in rows]
    
    # Calculate next_expected_release and determine display update date for each work
    for work in all_works:
        work_id = work["id"]
        # Get updates for this work
        updates_query = """
            SELECT email_date, work_word_count, chapter_word_count
            FROM updates
            WHERE work_id = ?
            ORDER BY email_date ASC
        """
        update_rows = cur.execute(updates_query, (work_id,)).fetchall()
        updates = [dict(row) for row in update_rows]
        
        # Calculate statistics including next_expected_release
        stats = calculate_work_statistics(updates, work)
        work["next_expected_release"] = stats.get("next_expected_release")
        
        # Determine display update date: use published_at for 1/1 or 1/? stories, otherwise updated_at
        chapters_current = work.get("chapters_current")
        chapters_max = work.get("chapters_max")
        
        # Edge case: 1/1 or 1/? chapter stories should use publish date
        if chapters_current == 1 and (chapters_max == 1 or chapters_max is None):
            work["display_update_date"] = work.get("published_at")
        else:
            # Use updated_at (last time work was actually updated on AO3)
            work["display_update_date"] = work.get("updated_at")
    
    # Sort works based on sort parameter
    if sort == "word_count":
        all_works.sort(key=lambda x: (x.get("total_word_count") is None, x.get("total_word_count") or 0), reverse=True)
    elif sort == "next_release":
        # Sort by next_expected_release descending (soonest dates first, None values go to end)
        # Use a tuple where first element ensures None goes to end, second element sorts dates ascending (soonest first)
        # But we reverse the whole thing so None stays at end but dates are in descending order
        # Actually, for "most to least recent" we want soonest first, which is ascending for dates
        # So we sort ascending but put None at the end by making None sort last
        def sort_key(x):
            release = x.get("next_expected_release")
            if release is None:
                return (1, "")  # None values sort to end
            return (0, release)  # Non-None values sort by date (ascending = soonest first)
        all_works.sort(key=sort_key)
    else:  # Default: sort by title
        all_works.sort(key=lambda x: (x.get("title") or "").lower())
    
    # Apply pagination
    offset = (page - 1) * page_size
    works = all_works[offset:offset + page_size]
    
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
            "filter": filter or "all",
            "sort": sort or "title",
        },
    )


# IMPORTANT: /works/scrape routes must be defined BEFORE /works/{work_id}
# Otherwise FastAPI will match /works/scrape as work_id="scrape"
@router.get("/works/scrape", response_class=HTMLResponse)
async def scrape_works_form(request: Request):
    """Show form for submitting AO3 work URLs to scrape."""
    return templates.TemplateResponse(
        "scrape_works.html",
        {
            "request": request,
        },
    )


@router.post("/works/scrape", response_class=HTMLResponse)
async def scrape_works_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    urls: str = Form(...),
    force_rescrape: bool = Form(False),
    login: bool = Form(False),
):
    """Process URL submission and scrape metadata."""
    from ao3tracker.downloader_service import create_job, execute_job
    
    # Parse URLs (one per line)
    url_list = [url.strip() for url in urls.split("\n") if url.strip()]
    
    if not url_list:
        return templates.TemplateResponse(
            "scrape_works.html",
            {
                "request": request,
                "error": "No URLs provided",
            },
        )
    
    try:
        # Create a scrape job for progress tracking
        params = {
            "urls": url_list,
            "force_rescrape": force_rescrape,
            "login": login,
        }
        job_id = create_job("scrape_works", params)
        background_tasks.add_task(execute_job, job_id, background_tasks)
        
        # Redirect to job detail page
        return RedirectResponse(url=f"/downloader/job/{job_id}", status_code=303)
    except Exception as e:
        return templates.TemplateResponse(
            "scrape_works.html",
            {
                "request": request,
                "error": f"Error creating scrape job: {str(e)}",
            },
        )


@router.get("/works/{work_id}", response_class=HTMLResponse)
async def work_detail(work_id: int, request: Request):
    conn = get_connection()
    cur = conn.cursor()

    work_row = cur.execute("""
        SELECT
            w.id,
            w.ao3_id,
            w.title,
            w.author,
            w.url,
            w.last_update_at,
            w.total_word_count,
            (SELECT u.chapter_label 
             FROM updates u 
             WHERE u.work_id = w.id 
             ORDER BY u.email_date DESC, u.id DESC 
             LIMIT 1) AS last_seen_chapter
        FROM works w
        WHERE w.id = ?
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


@router.post("/works/{work_id}/mark-read", response_class=HTMLResponse)
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
    return RedirectResponse(url=f"/works/{work_id}", status_code=303)


@router.get("/search", response_class=HTMLResponse)
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


@router.get("/status", response_class=HTMLResponse)
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


@router.get("/health", response_class=PlainTextResponse)
async def health():
    """Health check endpoint."""
    return "OK"

