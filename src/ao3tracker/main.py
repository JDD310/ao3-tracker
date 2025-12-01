from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from ao3tracker import routes_api, routes_html
from ao3tracker.db import init_db

logger = logging.getLogger(__name__)

# Import downloader routes with error handling
try:
    from ao3tracker import routes_downloader, routes_downloader_html
    DOWNLOADER_ROUTES_AVAILABLE = True
except Exception as e:
    print(f"Warning: Could not import downloader routes: {e}")
    import traceback
    traceback.print_exc()
    DOWNLOADER_ROUTES_AVAILABLE = False
    routes_downloader = None
    routes_downloader_html = None

# Get project root (same level as src/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Set up static directory
STATIC_DIR = BASE_DIR / "static"

# Create FastAPI app instance
app = FastAPI(title="AO3 Subscription Tracker")

# Mount static files at /static
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Add favicon route
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve favicon.ico to prevent 404 errors."""
    favicon_path = STATIC_DIR / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(favicon_path)
    # Return a simple 204 No Content if favicon doesn't exist
    from fastapi.responses import Response
    return Response(status_code=204)

# Initialize database (creates tables and runs migrations if needed)
init_db()

# Register routers
app.include_router(routes_html.router)
app.include_router(routes_api.router)


async def run_imap_ingestion():
    """Run IMAP ingestion in a thread pool."""
    try:
        from ao3tracker.ingest_imap import ingest_new_ao3_emails_imap
        import asyncio as aio
        
        # Run the synchronous ingestion function in a thread pool
        await aio.to_thread(ingest_new_ao3_emails_imap, max_messages=100)
        logger.info("IMAP ingestion completed successfully")
    except Exception as e:
        logger.error(f"Error during IMAP ingestion: {e}", exc_info=True)


async def periodic_imap_ingestion():
    """Background task that runs IMAP ingestion every 15 minutes."""
    # Wait a bit before first run to let the server start up
    await asyncio.sleep(30)
    
    while True:
        try:
            await run_imap_ingestion()
        except Exception as e:
            logger.error(f"Error in periodic IMAP ingestion task: {e}", exc_info=True)
        
        # Wait 15 minutes before next run
        await asyncio.sleep(15 * 60)


@app.on_event("startup")
async def startup_event():
    """Start background tasks when the application starts."""
    # Start the periodic IMAP ingestion task
    asyncio.create_task(periodic_imap_ingestion())
    logger.info("Started periodic IMAP ingestion task (runs every 15 minutes)")

# Set up templates for downloader (always available)
from fastapi.templating import Jinja2Templates
TEMPLATES_DIR = BASE_DIR / "templates"
downloader_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Register downloader routers (with error handling)
downloader_router_registered = False
if DOWNLOADER_ROUTES_AVAILABLE:
    try:
        if routes_downloader:
            app.include_router(routes_downloader.router)
        if routes_downloader_html:
            app.include_router(routes_downloader_html.router)
            downloader_router_registered = True
            print("✓ Downloader routes registered successfully")
    except Exception as e:
        print(f"Warning: Failed to register downloader routes: {e}")
        import traceback
        traceback.print_exc()

# Always create /downloader route to ensure it works
# If router was registered, this won't conflict (router routes take precedence)
# If router wasn't registered, this provides the fallback
@app.get("/downloader", response_class=HTMLResponse)
@app.get("/downloader/", response_class=HTMLResponse)
async def downloader_page(request: Request):
    """Downloader page - uses router if available, otherwise fallback."""
    # If router was registered, this route won't be called (router takes precedence)
    # But we keep it as a safety net
    if not downloader_router_registered:
        print("⚠ Using fallback downloader route")
    
    # Try to use router functions if available
    try:
        if DOWNLOADER_ROUTES_AVAILABLE and routes_downloader_html:
            # Import the function from the router module
            from ao3tracker.routes_downloader_html import downloader_page as router_downloader_page
            return await router_downloader_page(request)
    except Exception as e:
        print(f"Warning: Could not use router function: {e}")
    
    # Fallback: render template directly
    return downloader_templates.TemplateResponse(
        "downloader.html",
        {
            "request": request,
            "settings": {"download_folder": "downloads"},
            "recent_jobs": [],
            "error": "Downloader modules failed to load. Please check server logs for import errors." if not downloader_router_registered else None,
        },
    )

