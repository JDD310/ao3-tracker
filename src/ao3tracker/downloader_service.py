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
            self.cancelled = False
        def update(self, message: str):
            if self.update_func:
                self.update_func(message)
            self.messages.append(message)
        def is_cancelled(self) -> bool:
            return self.cancelled
        def cancel(self):
            self.cancelled = True
    
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
# Store cancellation flags for jobs
_cancelled_jobs: set[int] = set()


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
    
    # Check if job was cancelled before starting
    if job_id in _cancelled_jobs:
        update_job_status(job_id, "cancelled", progress="Job was cancelled before execution")
        _cancelled_jobs.discard(job_id)
        return
    
    update_job_status(job_id, "running", progress="Initializing job...")
    
    # Create progress callback
    progress_callback = ProgressCallback(
        lambda msg: update_job_status(job_id, "running", progress=msg)
    )
    _active_jobs[job_id] = progress_callback
    
    try:
        job_type = job["job_type"]
        params = job["parameters"]
        
        if not DOWNLOADER_WRAPPERS_AVAILABLE:
            raise ImportError("ao3downloader wrappers are not available. Please ensure ao3downloader is properly installed.")
        
        result = None
        
        if job_type == "download_from_ao3_link":
            if not params.get("link"):
                raise ValueError("Link parameter is required")
            # Decrypt password if present
            password = params.get("password")
            if password:
                from ao3tracker.password_utils import decrypt_password
                try:
                    password = decrypt_password(password)
                except Exception:
                    password = None  # If decryption fails, treat as no password
            result = await download_from_ao3_link(
                link=params["link"],
                file_types=params.get("file_types", ["EPUB"]),
                pages=params.get("pages"),
                include_series=params.get("include_series", False),
                download_images=params.get("download_images", False),
                login=params.get("login", False),
                username=params.get("username"),
                password=password,
                progress_callback=progress_callback,
            )
            # Clear password from memory
            if password:
                password = None
        
        elif job_type == "get_links_only":
            if not params.get("link"):
                raise ValueError("Link parameter is required")
            # Decrypt password if present
            password = params.get("password")
            if password:
                from ao3tracker.password_utils import decrypt_password
                try:
                    password = decrypt_password(password)
                except Exception:
                    password = None
            result = await get_links_only(
                link=params["link"],
                pages=params.get("pages"),
                include_series=params.get("include_series", False),
                include_metadata=params.get("include_metadata", False),
                login=params.get("login", False),
                username=params.get("username"),
                password=password,
                progress_callback=progress_callback,
            )
            # Clear password from memory
            if password:
                password = None
        
        elif job_type == "download_from_file":
            if not params.get("file_content"):
                raise ValueError("File content parameter is required")
            # Decrypt password if present
            password = params.get("password")
            if password:
                from ao3tracker.password_utils import decrypt_password
                try:
                    password = decrypt_password(password)
                except Exception:
                    password = None
            result = await download_from_file(
                file_content=params["file_content"],
                file_types=params.get("file_types", ["EPUB"]),
                include_series=params.get("include_series", True),
                download_images=params.get("download_images", False),
                login=params.get("login", False),
                username=params.get("username"),
                password=password,
                progress_callback=progress_callback,
            )
            # Clear password from memory
            if password:
                password = None
        
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
            # Decrypt password if present
            password = params.get("password")
            if password:
                from ao3tracker.password_utils import decrypt_password
                try:
                    password = decrypt_password(password)
                except Exception:
                    password = None
            result = await download_marked_for_later(
                login=params.get("login", True),
                mark_as_read=params.get("mark_as_read", True),
                username=params.get("username"),
                password=password,
                progress_callback=progress_callback,
            )
            # Clear password from memory
            if password:
                password = None
        
        elif job_type == "download_pinboard_bookmarks":
            if not params.get("api_token"):
                raise ValueError("API token is required")
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
            if not params.get("links"):
                raise ValueError("Links parameter is required")
            result = await configure_ignore_list(
                links=params["links"],
                check_deleted=params.get("check_deleted", False),
                progress_callback=progress_callback,
            )
        
        elif job_type == "scrape_works":
            from ao3tracker.scrape_works import scrape_and_store_works
            import asyncio
            
            if not params.get("urls"):
                raise ValueError("URLs parameter is required")
            
            # Decrypt password if present
            password = params.get("password")
            if password:
                from ao3tracker.password_utils import decrypt_password
                try:
                    password = decrypt_password(password)
                except Exception:
                    password = None
            
            # Run scraping in thread pool with progress callback
            def _scrape():
                return scrape_and_store_works(
                    urls=params["urls"],
                    force_rescrape=params.get("force_rescrape", False),
                    login=params.get("login", False),
                    username=params.get("username"),
                    password=password,
                    progress_callback=lambda msg: progress_callback.update(msg),
                )
            
            # Clear password after use
            if password:
                password = None
            
            stats = await asyncio.to_thread(_scrape)
            result = {
                "success": True,
                "processed": stats["processed"],
                "inserted": stats["inserted"],
                "updated": stats["updated"],
                "errors": stats["errors"],
                "message": f"Processed {stats['processed']} URLs: {stats['inserted']} inserted, {stats['updated']} updated, {len(stats['errors'])} errors",
            }
        
        else:
            raise ValueError(f"Unknown job type: {job_type}")
        
        # Check if job was cancelled during execution
        if job_id in _cancelled_jobs or progress_callback.is_cancelled():
            update_job_status(job_id, "cancelled", progress="Job was cancelled by user")
            _cancelled_jobs.discard(job_id)
            return
        
        # Check result
        if result is None:
            update_job_status(job_id, "failed", error="Job returned no result")
        elif result.get("success"):
            update_job_status(job_id, "completed", result=result, progress="Job completed successfully")
        else:
            error_msg = result.get("error", "Job failed without error message")
            update_job_status(job_id, "failed", error=error_msg)
    
    except ImportError as e:
        # Check if cancellation caused the exception
        if job_id in _cancelled_jobs or progress_callback.is_cancelled():
            update_job_status(job_id, "cancelled", progress="Job was cancelled by user")
            _cancelled_jobs.discard(job_id)
        else:
            error_msg = f"Import error: {str(e)}. Please ensure ao3downloader is properly installed."
            update_job_status(job_id, "failed", error=error_msg, progress=error_msg)
    except ValueError as e:
        # Check if cancellation caused the exception
        if job_id in _cancelled_jobs or progress_callback.is_cancelled():
            update_job_status(job_id, "cancelled", progress="Job was cancelled by user")
            _cancelled_jobs.discard(job_id)
        else:
            error_msg = f"Invalid parameters: {str(e)}"
            update_job_status(job_id, "failed", error=error_msg, progress=error_msg)
    except Exception as e:
        # Check if cancellation caused the exception
        if job_id in _cancelled_jobs or progress_callback.is_cancelled():
            update_job_status(job_id, "cancelled", progress="Job was cancelled by user")
            _cancelled_jobs.discard(job_id)
        else:
            import traceback
            error_msg = f"Unexpected error: {str(e)}"
            error_details = traceback.format_exc()
            update_job_status(job_id, "failed", error=error_msg, progress=error_msg)
            # Log full traceback for debugging
            print(f"Job {job_id} error traceback:\n{error_details}")
    
    finally:
        # Remove from active jobs and cancelled set
        _active_jobs.pop(job_id, None)
        _cancelled_jobs.discard(job_id)


def get_progress(job_id: int) -> Optional[str]:
    """Get current progress message for a job."""
    callback = _active_jobs.get(job_id)
    if callback and callback.messages:
        return callback.messages[-1]
    
    job = get_job(job_id)
    if job:
        return job.get("progress_message")
    
    return None


def cancel_job(job_id: int) -> bool:
    """
    Cancel a running or pending job.
    
    Returns:
        True if job was cancelled, False if job not found or not running
    """
    job = get_job(job_id)
    if not job:
        return False
    
    # If job is already completed/failed/cancelled, can't cancel
    if job["status"] in ("completed", "failed", "cancelled"):
        return False
    
    # Mark job as cancelled
    _cancelled_jobs.add(job_id)
    
    # If job is running, cancel its progress callback
    callback = _active_jobs.get(job_id)
    if callback:
        callback.cancel()
    
    # Update job status
    if job["status"] == "running":
        update_job_status(job_id, "cancelled", progress="Job cancelled by user")
    else:
        # Job is pending, mark as cancelled
        update_job_status(job_id, "cancelled", progress="Job cancelled before execution")
    
    return True

