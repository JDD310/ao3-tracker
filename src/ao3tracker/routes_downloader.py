"""API routes for ao3downloader integration."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from ao3tracker.downloader_config import get_all_settings, get_setting, set_setting
from ao3tracker.downloader_service import (
    create_job,
    execute_job,
    get_job,
    get_progress,
    list_jobs,
)

router = APIRouter(prefix="/api/v1/downloader", tags=["downloader"])


# Request models
class DownloadFromLinkRequest(BaseModel):
    link: str
    file_types: List[str] = ["EPUB"]
    pages: Optional[int] = None
    include_series: bool = False
    download_images: bool = False
    login: bool = False


class GetLinksRequest(BaseModel):
    link: str
    pages: Optional[int] = None
    include_series: bool = False
    include_metadata: bool = False
    login: bool = False


class DownloadFromFileRequest(BaseModel):
    file_content: str
    file_types: List[str] = ["EPUB"]
    include_series: bool = True
    download_images: bool = False
    login: bool = False


class UpdateIncompleteRequest(BaseModel):
    folder_path: str
    file_types: List[str] = ["EPUB"]


class DownloadMissingSeriesRequest(BaseModel):
    folder_path: str
    file_types: List[str] = ["EPUB"]


class RedownloadRequest(BaseModel):
    folder_path: str
    source_format: str
    target_formats: List[str]


class MarkedForLaterRequest(BaseModel):
    login: bool = True
    mark_as_read: bool = True


class PinboardRequest(BaseModel):
    api_token: str
    include_unread: bool = True
    date_from: Optional[str] = None


class IgnoreListRequest(BaseModel):
    links: List[str]
    check_deleted: bool = False


# Job creation endpoints
@router.post("/jobs/download-from-link")
async def create_download_job(
    request: DownloadFromLinkRequest,
    background_tasks: BackgroundTasks,
):
    """Create a job to download from an AO3 link."""
    job_id = create_job("download_from_ao3_link", request.model_dump())
    background_tasks.add_task(execute_job, job_id, background_tasks)
    return {"job_id": job_id, "status": "pending"}


@router.post("/jobs/get-links")
async def create_get_links_job(
    request: GetLinksRequest,
    background_tasks: BackgroundTasks,
):
    """Create a job to get links only."""
    job_id = create_job("get_links_only", request.model_dump())
    background_tasks.add_task(execute_job, job_id, background_tasks)
    return {"job_id": job_id, "status": "pending"}


@router.post("/jobs/download-from-file")
async def create_download_from_file_job(
    request: DownloadFromFileRequest,
    background_tasks: BackgroundTasks,
):
    """Create a job to download from a file."""
    job_id = create_job("download_from_file", request.model_dump())
    background_tasks.add_task(execute_job, job_id, background_tasks)
    return {"job_id": job_id, "status": "pending"}


@router.post("/jobs/update-incomplete")
async def create_update_incomplete_job(
    request: UpdateIncompleteRequest,
    background_tasks: BackgroundTasks,
):
    """Create a job to update incomplete fics."""
    job_id = create_job("update_incomplete_fics", request.model_dump())
    background_tasks.add_task(execute_job, job_id, background_tasks)
    return {"job_id": job_id, "status": "pending"}


@router.post("/jobs/download-missing-series")
async def create_download_missing_series_job(
    request: DownloadMissingSeriesRequest,
    background_tasks: BackgroundTasks,
):
    """Create a job to download missing fics from series."""
    job_id = create_job("download_missing_from_series", request.model_dump())
    background_tasks.add_task(execute_job, job_id, background_tasks)
    return {"job_id": job_id, "status": "pending"}


@router.post("/jobs/redownload")
async def create_redownload_job(
    request: RedownloadRequest,
    background_tasks: BackgroundTasks,
):
    """Create a job to re-download in different format."""
    job_id = create_job("redownload_in_different_format", request.model_dump())
    background_tasks.add_task(execute_job, job_id, background_tasks)
    return {"job_id": job_id, "status": "pending"}


@router.post("/jobs/marked-for-later")
async def create_marked_for_later_job(
    request: MarkedForLaterRequest,
    background_tasks: BackgroundTasks,
):
    """Create a job to download marked for later list."""
    job_id = create_job("download_marked_for_later", request.model_dump())
    background_tasks.add_task(execute_job, job_id, background_tasks)
    return {"job_id": job_id, "status": "pending"}


@router.post("/jobs/pinboard")
async def create_pinboard_job(
    request: PinboardRequest,
    background_tasks: BackgroundTasks,
):
    """Create a job to download Pinboard bookmarks."""
    job_id = create_job("download_pinboard_bookmarks", request.model_dump())
    background_tasks.add_task(execute_job, job_id, background_tasks)
    return {"job_id": job_id, "status": "pending"}


@router.post("/jobs/log-visualization")
async def create_log_visualization_job(
    background_tasks: BackgroundTasks,
):
    """Create a job to generate log visualization."""
    job_id = create_job("generate_log_visualization", {})
    background_tasks.add_task(execute_job, job_id, background_tasks)
    return {"job_id": job_id, "status": "pending"}


@router.post("/jobs/ignore-list")
async def create_ignore_list_job(
    request: IgnoreListRequest,
    background_tasks: BackgroundTasks,
):
    """Create a job to configure ignore list."""
    job_id = create_job("configure_ignore_list", request.model_dump())
    background_tasks.add_task(execute_job, job_id, background_tasks)
    return {"job_id": job_id, "status": "pending"}


# Job status endpoints
@router.get("/jobs")
async def get_jobs(
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None),
):
    """List all jobs, optionally filtered by status."""
    jobs = list_jobs(limit=limit, status=status)
    return {"jobs": jobs, "total": len(jobs)}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: int):
    """Get job status by ID."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs/{job_id}/progress")
async def get_job_progress(job_id: int):
    """Get current progress message for a job."""
    progress = get_progress(job_id)
    if progress is None:
        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        progress = job.get("progress_message", "")
    return {"job_id": job_id, "progress": progress}


# Settings endpoints
@router.get("/settings")
async def get_settings():
    """Get all downloader settings."""
    return get_all_settings()


@router.post("/settings")
async def update_settings(settings: dict):
    """Update downloader settings."""
    for key, value in settings.items():
        set_setting(key, value)
    return {"status": "success", "message": "Settings updated"}


@router.get("/settings/{key}")
async def get_setting_value(key: str):
    """Get a specific setting value."""
    value = get_setting(key)
    return {"key": key, "value": value}

