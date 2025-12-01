from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ao3tracker import routes_api, routes_html
from ao3tracker.db import init_db

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

# Initialize database (creates tables and runs migrations if needed)
init_db()

# Register routers
app.include_router(routes_html.router)
app.include_router(routes_api.router)

# Register downloader routers (with error handling)
if DOWNLOADER_ROUTES_AVAILABLE and routes_downloader and routes_downloader_html:
    try:
        app.include_router(routes_downloader.router)
        app.include_router(routes_downloader_html.router)
        print("✓ Downloader routes registered successfully")
    except Exception as e:
        print(f"Warning: Failed to register downloader routes: {e}")
        import traceback
        traceback.print_exc()
else:
    print("⚠ Downloader routes not available - check import errors above")
    
    # Add a simple fallback route so the page at least loads
    @app.get("/downloader", response_class=HTMLResponse)
    async def downloader_fallback(request: Request):
        from fastapi.templating import Jinja2Templates
        from pathlib import Path
        BASE_DIR = Path(__file__).resolve().parent.parent.parent
        templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
        return templates.TemplateResponse(
            "downloader.html",
            {
                "request": request,
                "settings": {"download_folder": "downloads"},
                "recent_jobs": [],
                "error": "Downloader modules failed to load. Please check server logs for import errors.",
            },
        )

