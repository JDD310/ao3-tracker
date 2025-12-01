from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UpdateBase(BaseModel):
    """Base model for update data."""
    chapter_label: Optional[str] = None
    email_subject: Optional[str] = None
    email_date: Optional[str] = None
    chapter_word_count: Optional[int] = None
    work_word_count: Optional[int] = None
    is_read: bool = False


class Update(UpdateBase):
    """Update model with ID."""
    id: int
    work_id: int
    created_at: Optional[str] = None


class WorkBase(BaseModel):
    """Base model for work data."""
    ao3_id: str
    title: str
    author: str
    url: Optional[str] = None
    last_seen_chapter: Optional[str] = None
    last_update_at: Optional[str] = None
    total_word_count: Optional[int] = None
    # New metadata fields from scraping
    fandoms: Optional[str] = None
    rating: Optional[str] = None
    archive_warnings: Optional[str] = None
    categories: Optional[str] = None
    relationships: Optional[str] = None
    characters: Optional[str] = None
    additional_tags: Optional[str] = None
    language: Optional[str] = None
    chapters_current: Optional[int] = None
    chapters_max: Optional[int] = None
    status: Optional[str] = None
    published_at: Optional[str] = None
    updated_at: Optional[str] = None
    summary_html: Optional[str] = None
    metadata_source: Optional[str] = None


class Work(WorkBase):
    """Work model with ID."""
    id: int


class UpdateWithWork(Update):
    """Update model with work information."""
    work_title: str
    work_author: str
    work_url: Optional[str] = None


class WorkDetail(Work):
    """Work detail model with updates."""
    updates: list[Update] = []


class PaginatedResponse(BaseModel):
    """Generic paginated response."""
    items: list
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total_pages: int


class UpdatesResponse(PaginatedResponse):
    """Paginated updates response."""
    items: list[UpdateWithWork]


class WorksResponse(PaginatedResponse):
    """Paginated works response."""
    items: list[Work]

