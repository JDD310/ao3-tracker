from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ao3tracker.db import get_connection, mark_updates_as_read
from ao3tracker.models import (
    Update,
    UpdateWithWork,
    UpdatesResponse,
    Work,
    WorkDetail,
    WorksResponse,
)
from ao3tracker.scrape_works import scrape_and_store_works

router = APIRouter(prefix="/api/v1", tags=["api"])


@router.get("/updates", response_model=UpdatesResponse)
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


@router.get("/works", response_model=WorksResponse)
async def api_list_works(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    author: Optional[str] = None,
    filter: Optional[str] = Query(None, description="Filter: 'updated' for works with updates, 'all' for all works"),
):
    """List works with pagination and filtering."""
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
    
    # Get paginated results with most recent chapter label
    offset = (page - 1) * page_size
    query = f"""
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
        WHERE {where_clause}
        ORDER BY w.title ASC
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


@router.get("/works/{work_id}", response_model=WorkDetail)
async def api_work_detail(work_id: int):
    """Get work details with updates."""
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


@router.post("/works/{work_id}/mark-read")
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


class ScrapeRequest(BaseModel):
    """Request model for scraping works from URLs."""
    urls: list[str]
    force_rescrape: bool = False
    login: bool = False
    username: Optional[str] = None
    password: Optional[str] = None  # Required if login=True, encrypted in memory


@router.post("/works/scrape-from-urls")
async def api_scrape_works_from_urls(request: ScrapeRequest):
    """
    Scrape metadata from AO3 work URLs and store in database.
    
    Request body:
        - urls: List of AO3 work URLs
        - force_rescrape: If True, rescrape even if work exists (default: False)
    
    Returns:
        Status and statistics about the scraping operation
    """
    if not request.urls:
        raise HTTPException(status_code=400, detail="At least one URL is required")
    
    try:
        # Password should be provided in plaintext from API, but we encrypt it if needed
        # For API, we expect plaintext password and use it directly
        password = request.password
        
        stats = scrape_and_store_works(
            request.urls,
            force_rescrape=request.force_rescrape,
            login=request.login,
            username=request.username,
            password=password,
        )
        
        # Clear password from memory
        if password:
            password = None
        
        return {
            "status": "success",
            "processed": stats["processed"],
            "inserted": stats["inserted"],
            "updated": stats["updated"],
            "errors": stats["errors"],
            "message": f"Processed {stats['processed']} URLs: {stats['inserted']} inserted, {stats['updated']} updated, {len(stats['errors'])} errors",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during scraping: {str(e)}")

