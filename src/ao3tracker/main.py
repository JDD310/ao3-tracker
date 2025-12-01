from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ao3tracker import routes_api, routes_html
from ao3tracker.db import init_db

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

