"""HTML routes for ao3downloader integration."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

try:
    from ao3tracker.downloader_config import get_all_settings, get_download_folder
    from ao3tracker.downloader_service import create_job, execute_job, get_job, list_jobs
    DOWNLOADER_AVAILABLE = True
except Exception as e:
    # If downloader modules fail to import, create stub functions
    DOWNLOADER_AVAILABLE = False
    import traceback
    traceback.print_exc()
    
    def get_all_settings():
        return {"download_folder": "downloads"}
    
    def get_download_folder():
        from pathlib import Path
        return Path("downloads")
    
    def create_job(*args, **kwargs):
        raise NotImplementedError("Downloader not available - check imports")
    
    def execute_job(*args, **kwargs):
        pass
    
    def get_job(*args, **kwargs):
        return None
    
    def list_jobs(*args, **kwargs):
        return []

# Get project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["downloader-html"])


@router.get("/downloader", response_class=HTMLResponse)
@router.get("/downloader/", response_class=HTMLResponse)  # Also handle trailing slash
async def downloader_page(request: Request):
    """Main downloader page with all actions."""
    if not DOWNLOADER_AVAILABLE:
        return templates.TemplateResponse(
            "downloader.html",
            {
                "request": request,
                "settings": {"download_folder": "downloads"},
                "recent_jobs": [],
                "error": "Downloader modules not available. Please install ao3downloader: pip install ao3downloader",
            },
        )
    
    try:
        settings = get_all_settings()
    except Exception as e:
        # Fallback to defaults if settings fail
        try:
            settings = {"download_folder": str(get_download_folder())}
        except:
            settings = {"download_folder": "downloads"}
    
    try:
        recent_jobs = list_jobs(limit=10)
    except Exception as e:
        # Fallback to empty list if jobs fail
        recent_jobs = []
    
    return templates.TemplateResponse(
        "downloader.html",
        {
            "request": request,
            "settings": settings,
            "recent_jobs": recent_jobs,
        },
    )


@router.get("/downloader/job/{job_id}", response_class=HTMLResponse)
async def job_detail_page(request: Request, job_id: int):
    """View job details."""
    job = get_job(job_id)
    if not job:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Job not found")
    
    return templates.TemplateResponse(
        "downloader_job.html",
        {
            "request": request,
            "job": job,
        },
    )


@router.post("/downloader/download-from-link", response_class=HTMLResponse)
async def submit_download_from_link(
    request: Request,
    background_tasks: BackgroundTasks,
    link: str = Form(...),
    pages: Optional[str] = Form(None),
    include_series: bool = Form(False),
    download_images: bool = Form(False),
    login: bool = Form(False),
):
    """Submit download from link job."""
    # Get file types from form (can be multiple)
    form_data = await request.form()
    file_types_list = form_data.getlist("file_types")
    if not file_types_list:
        file_types_list = ["EPUB"]  # Default
    
    pages_int = int(pages) if pages and pages.isdigit() else None
    
    params = {
        "link": link,
        "file_types": file_types_list,
        "pages": pages_int,
        "include_series": include_series,
        "download_images": download_images,
        "login": login,
    }
    
    job_id = create_job("download_from_ao3_link", params)
    background_tasks.add_task(execute_job, job_id, background_tasks)
    
    return RedirectResponse(url=f"/downloader/job/{job_id}", status_code=303)


@router.post("/downloader/get-links", response_class=HTMLResponse)
async def submit_get_links(
    request: Request,
    background_tasks: BackgroundTasks,
    link: str = Form(...),
    pages: Optional[str] = Form(None),
    include_series: bool = Form(False),
    include_metadata: bool = Form(False),
    login: bool = Form(False),
):
    """Submit get links job."""
    pages_int = int(pages) if pages and pages.isdigit() else None
    
    params = {
        "link": link,
        "pages": pages_int,
        "include_series": include_series,
        "include_metadata": include_metadata,
        "login": login,
    }
    
    job_id = create_job("get_links_only", params)
    background_tasks.add_task(execute_job, job_id, background_tasks)
    
    return RedirectResponse(url=f"/downloader/job/{job_id}", status_code=303)


@router.post("/downloader/download-from-file", response_class=HTMLResponse)
async def submit_download_from_file(
    request: Request,
    background_tasks: BackgroundTasks,
    file_content: str = Form(...),
    include_series: bool = Form(True),
    download_images: bool = Form(False),
    login: bool = Form(False),
):
    """Submit download from file job."""
    # Get file types from form (can be multiple)
    form_data = await request.form()
    file_types_list = form_data.getlist("file_types")
    if not file_types_list:
        file_types_list = ["EPUB"]  # Default
    
    params = {
        "file_content": file_content,
        "file_types": file_types_list,
        "include_series": include_series,
        "download_images": download_images,
        "login": login,
    }
    
    job_id = create_job("download_from_file", params)
    background_tasks.add_task(execute_job, job_id, background_tasks)
    
    return RedirectResponse(url=f"/downloader/job/{job_id}", status_code=303)

