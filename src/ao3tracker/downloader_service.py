"""Service layer for managing download jobs."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks

from ao3tracker.db import get_connection

try:
    from ao3tracker.downloader_wrappers import (
        ProgressCallback,
        configure_ignore_list,
        download_from_ao3_link,
        download_from_file,
        download_marked_for_later,
        download_missing_from_series,
        download_pinboard_bookmarks,
        generate_log_visualization,
        get_links_only,
        redownload_in_different_format,
        update_incomplete_fics,
    )
    DOWNLOADER_WRAPPERS_AVAILABLE = True
except ImportError as e:
    # If wrappers aren't available, create stub classes/functions
    DOWNLOADER_WRAPPERS_AVAILABLE = False
    
    class ProgressCallback:
        def __init__(self, update_func=None):
            self.update_func = update_func
            self.messages = []
        def update(self, message: str):
            if self.update_func:
                self.update_func(message)
            self.messages.append(message)
    
    async def download_from_ao3_link(*args, **kwargs):
        return {"success": False, "error": "ao3downloader not installed"}
    async def get_links_only(*args, **kwargs):
        return {"success": False, "error": "ao3downloader not installed"}
    async def download_from_file(*args, **kwargs):
        return {"success": False, "error": "ao3downloader not installed"}
    async def update_incomplete_fics(*args, **kwargs):
        return {"success": False, "error": "ao3downloader not installed"}
    async def download_missing_from_series(*args, **kwargs):
        return {"success": False, "error": "ao3downloader not installed"}
    async def redownload_in_different_format(*args, **kwargs):
        return {"success": False, "error": "ao3downloader not installed"}
    async def download_marked_for_later(*args, **kwargs):
        return {"success": False, "error": "ao3downloader not installed"}
    async def download_pinboard_bookmarks(*args, **kwargs):
        return {"success": False, "error": "ao3downloader not installed"}
    async def generate_log_visualization(*args, **kwargs):
        return {"success": False, "error": "ao3downloader not installed"}
    async def configure_ignore_list(*args, **kwargs):
        return {"success": False, "error": "ao3downloader not installed"}


# Store active job callbacks for progress updates
_active_jobs: Dict[int, ProgressCallback] = {}


def create_job(job_type: str, parameters: Dict[str, Any]) -> int:
    """Create a new download job and return its ID."""
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO download_jobs (job_type, status, parameters)
        VALUES (?, 'pending', ?)
    """, (job_type, json.dumps(parameters)))
    
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    
    return job_id


def update_job_status(
    job_id: int,
    status: str,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    progress: Optional[str] = None,
) -> None:
    """Update job status and results."""
    conn = get_connection()
    cur = conn.cursor()
    
    updates = []
    params = []
    
    if status:
        updates.append("status = ?")
        params.append(status)
    
    if result is not None:
        updates.append("result = ?")
        params.append(json.dumps(result))
    
    if error:
        updates.append("error_message = ?")
        params.append(error)
    
    if progress:
        updates.append("progress_message = ?")
        params.append(progress)
    
    if status == "running" and not any("started_at" in s for s in updates):
        updates.append("started_at = CURRENT_TIMESTAMP")
    
    if status in ("completed", "failed"):
        updates.append("completed_at = CURRENT_TIMESTAMP")
    
    params.append(job_id)
    
    if updates:
        query = f"UPDATE download_jobs SET {', '.join(updates)} WHERE id = ?"
        cur.execute(query, params)
        conn.commit()
    
    conn.close()


def get_job(job_id: int) -> Optional[Dict[str, Any]]:
    """Get job by ID."""
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT id, job_type, status, parameters, result, error_message,
               progress_message, created_at, started_at, completed_at
        FROM download_jobs
        WHERE id = ?
    """, (job_id,))
    
    row = cur.fetchone()
    conn.close()
    
    if row is None:
        return None
    
    job = dict(row)
    if job["parameters"]:
        job["parameters"] = json.loads(job["parameters"])
    if job["result"]:
        job["result"] = json.loads(job["result"])
    
    return job


def list_jobs(limit: int = 50, status: Optional[str] = None) -> list[Dict[str, Any]]:
    """List jobs, optionally filtered by status."""
    conn = get_connection()
    cur = conn.cursor()
    
    if status:
        cur.execute("""
            SELECT id, job_type, status, parameters, result, error_message,
                   progress_message, created_at, started_at, completed_at
            FROM download_jobs
            WHERE status = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (status, limit))
    else:
        cur.execute("""
            SELECT id, job_type, status, parameters, result, error_message,
                   progress_message, created_at, started_at, completed_at
            FROM download_jobs
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
    
    rows = cur.fetchall()
    conn.close()
    
    jobs = []
    for row in rows:
        job = dict(row)
        if job["parameters"]:
            job["parameters"] = json.loads(job["parameters"])
        if job["result"]:
            job["result"] = json.loads(job["result"])
        jobs.append(job)
    
    return jobs


async def execute_job(job_id: int, background_tasks: BackgroundTasks) -> None:
    """Execute a download job asynchronously."""
    job = get_job(job_id)
    if not job:
        return
    
    update_job_status(job_id, "running")
    
    # Create progress callback
    progress_callback = ProgressCallback(
        lambda msg: update_job_status(job_id, "running", progress=msg)
    )
    _active_jobs[job_id] = progress_callback
    
    try:
        job_type = job["job_type"]
        params = job["parameters"]
        
        result = None
        
        if job_type == "download_from_ao3_link":
            result = await download_from_ao3_link(
                link=params["link"],
                file_types=params.get("file_types", ["EPUB"]),
                pages=params.get("pages"),
                include_series=params.get("include_series", False),
                download_images=params.get("download_images", False),
                login=params.get("login", False),
                progress_callback=progress_callback,
            )
        
        elif job_type == "get_links_only":
            result = await get_links_only(
                link=params["link"],
                pages=params.get("pages"),
                include_series=params.get("include_series", False),
                include_metadata=params.get("include_metadata", False),
                login=params.get("login", False),
                progress_callback=progress_callback,
            )
        
        elif job_type == "download_from_file":
            result = await download_from_file(
                file_content=params["file_content"],
                file_types=params.get("file_types", ["EPUB"]),
                include_series=params.get("include_series", True),
                download_images=params.get("download_images", False),
                login=params.get("login", False),
                progress_callback=progress_callback,
            )
        
        elif job_type == "update_incomplete_fics":
            result = await update_incomplete_fics(
                folder_path=params["folder_path"],
                file_types=params.get("file_types", ["EPUB"]),
                progress_callback=progress_callback,
            )
        
        elif job_type == "download_missing_from_series":
            result = await download_missing_from_series(
                folder_path=params["folder_path"],
                file_types=params.get("file_types", ["EPUB"]),
                progress_callback=progress_callback,
            )
        
        elif job_type == "redownload_in_different_format":
            result = await redownload_in_different_format(
                folder_path=params["folder_path"],
                source_format=params["source_format"],
                target_formats=params["target_formats"],
                progress_callback=progress_callback,
            )
        
        elif job_type == "download_marked_for_later":
            result = await download_marked_for_later(
                login=params.get("login", True),
                mark_as_read=params.get("mark_as_read", True),
                progress_callback=progress_callback,
            )
        
        elif job_type == "download_pinboard_bookmarks":
            result = await download_pinboard_bookmarks(
                api_token=params["api_token"],
                include_unread=params.get("include_unread", True),
                date_from=params.get("date_from"),
                progress_callback=progress_callback,
            )
        
        elif job_type == "generate_log_visualization":
            result = await generate_log_visualization(
                progress_callback=progress_callback,
            )
        
        elif job_type == "configure_ignore_list":
            result = await configure_ignore_list(
                links=params["links"],
                check_deleted=params.get("check_deleted", False),
                progress_callback=progress_callback,
            )
        
        else:
            raise ValueError(f"Unknown job type: {job_type}")
        
        if result and result.get("success"):
            update_job_status(job_id, "completed", result=result)
        else:
            error_msg = result.get("error", "Job failed") if result else "Unknown error"
            update_job_status(job_id, "failed", error=error_msg)
    
    except Exception as e:
        update_job_status(job_id, "failed", error=str(e))
    
    finally:
        # Remove from active jobs
        _active_jobs.pop(job_id, None)


def get_progress(job_id: int) -> Optional[str]:
    """Get current progress message for a job."""
    callback = _active_jobs.get(job_id)
    if callback and callback.messages:
        return callback.messages[-1]
    
    job = get_job(job_id)
    if job:
        return job.get("progress_message")
    
    return None

