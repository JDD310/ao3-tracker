"""Adapter module for integrating ao3downloader into ao3-tracker."""

from __future__ import annotations

import re
import sys
from datetime import datetime
from typing import Any, Dict, Optional

# Ensure ao3downloader is installed, then add to path
from ao3tracker.downloader_setup import ensure_ao3downloader_installed

_AO3_DOWNLOADER_DIR = ensure_ao3downloader_installed()
if str(_AO3_DOWNLOADER_DIR) not in sys.path:
    sys.path.insert(0, str(_AO3_DOWNLOADER_DIR))

# Import from local repo
import ao3downloader.parse_soup as parse_soup
import ao3downloader.parse_text as parse_text
from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository


def extract_work_id(url: str) -> Optional[str]:
    """Extract numeric work ID from URL."""
    return parse_text.get_work_number(url)


def normalize_work_url(url: str) -> str:
    """Normalize URL to canonical /works/<id> format."""
    work_id = extract_work_id(url)
    if not work_id:
        raise ValueError(f"Could not extract work ID from URL: {url}")
    return f"https://archiveofourown.org/works/{work_id}"


def parse_chapters(chapters_str: str) -> tuple[Optional[int], Optional[int]]:
    """
    Parse chapter string (e.g., "5/10", "5", "-1") into current and max.
    
    Returns:
        (current, max) tuple. Either can be None if not available.
    """
    if not chapters_str or chapters_str == "-1":
        return None, None
    
    # Remove commas and whitespace
    chapters_str = chapters_str.replace(",", "").strip()
    
    if "/" in chapters_str:
        parts = chapters_str.split("/", 1)
        try:
            current = int(parts[0].strip()) if parts[0].strip() else None
            max_chapters = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else None
            return current, max_chapters
        except ValueError:
            return None, None
    else:
        try:
            current = int(chapters_str)
            return current, None
        except ValueError:
            return None, None


def parse_date(date_str: str) -> Optional[str]:
    """
    Parse date string to ISO8601 format.
    
    Handles various AO3 date formats like "2024-01-15" or "15 Jan 2024".
    """
    if not date_str:
        return None
    
    date_str = date_str.strip()
    
    # Try ISO format first
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.isoformat()
    except ValueError:
        pass
    
    # Try common date formats
    formats = [
        "%d %b %Y",  # 15 Jan 2024
        "%d %B %Y",  # 15 January 2024
        "%b %d, %Y",  # Jan 15, 2024
        "%B %d, %Y",  # January 15, 2024
        "%Y-%m-%d",  # 2024-01-15
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    
    # If all parsing fails, return as-is (might be in a format we don't recognize)
    return date_str


def parse_words(words_str: str) -> Optional[int]:
    """Parse word count string (may contain commas) to integer."""
    if not words_str:
        return None
    
    try:
        # Remove commas and whitespace
        words_str = words_str.replace(",", "").strip()
        return int(words_str) if words_str else None
    except ValueError:
        return None


def fetch_work_metadata_via_ao3_downloader(
    url: str, 
    login: bool = False, 
    username: str = None, 
    password: str = None,
    repo: Optional[Repository] = None
) -> Dict[str, Any]:
    """
    Fetch work metadata using ao3downloader.
    
    Args:
        url: AO3 work URL (will be normalized)
        login: Whether to login to AO3 (ignored if repo is provided - repo should already be logged in)
        username: AO3 username (if None, will try to get from settings)
        password: AO3 password (if None, will try to get from settings)
        repo: Optional Repository instance to reuse (if None, creates new one)
    
    Returns:
        Dict with keys matching database columns
    
    Raises:
        ValueError: If work is deleted or URL is invalid
        Exception: For network errors or locked works
    """
    # Normalize URL
    normalized_url = normalize_work_url(url)
    work_id = extract_work_id(normalized_url)
    
    # Use provided repo or create new one
    if repo is not None:
        # Reuse existing repository (should already be logged in if needed)
        soup = repo.get_soup(normalized_url)
    else:
        # Create new FileOps and Repository (for backward compatibility)
        fileops = FileOps()
        fileops.initialize()  # Ensure directories exist
        
        # Use Repository as context manager
        with Repository(fileops) as repo:
            # Login if requested
            if login:
                from ao3tracker.downloader_config import get_setting
                if not username:
                    username = get_setting("username", "")
                if not username or not password:
                    raise ValueError("Login requested but username and password are required. Please provide them in the request.")
                
                try:
                    repo.login(username, password)
                except Exception as e:
                    raise ValueError(f"Login failed: {str(e)}")
                finally:
                    # Clear password from memory
                    if password:
                        password = None
            
            # Fetch the work page
            soup = repo.get_soup(normalized_url)
            
            # Check for deleted works
            if parse_soup.is_deleted(soup):
                raise ValueError(f"Work {work_id} has been deleted")
            
            # Check for locked works (would need login to access)
            if parse_soup.is_locked(soup):
                if not login:
                    raise ValueError(f"Work {work_id} is locked and requires login. Please enable login option.")
                else:
                    # If we're logged in but still locked, there might be an issue
                    raise ValueError(f"Work {work_id} is locked and could not be accessed even with login")
            
            # Handle explicit content warning (proceed through it)
            if parse_soup.is_explicit(soup):
                proceed_url = parse_soup.get_proceed_link(soup)
                soup = repo.get_soup(proceed_url)
            
            # Extract metadata
            metadata = parse_soup.get_work_metadata_from_work(soup, normalized_url)
            
            # Parse chapters
            chapters_current, chapters_max = parse_chapters(metadata.get("chapters", ""))
            
            # Parse word count
            words = parse_words(metadata.get("words", ""))
            
            # Determine status (complete vs in-progress)
            # AO3 doesn't always provide this directly, but we can infer from chapters
            status = None
            if chapters_max is not None and chapters_current is not None:
                status = "complete" if chapters_current >= chapters_max else "in-progress"
            elif chapters_current is not None and chapters_max is None:
                # If we have current but no max, assume in-progress
                status = "in-progress"
            
            # Parse dates
            published_at = parse_date(metadata.get("published", ""))
            updated_at = parse_date(metadata.get("updated", ""))
            
            # Map ao3downloader metadata to our database format
            result = {
                "ao3_id": work_id,
                "title": metadata.get("title", ""),
                "author": metadata.get("author", ""),
                "url": normalized_url,
                "fandoms": metadata.get("fandom", ""),  # ao3downloader uses 'fandom' (singular)
                "rating": metadata.get("rating", ""),
                "archive_warnings": metadata.get("warning", ""),  # ao3downloader uses 'warning'
                "categories": metadata.get("category", ""),  # ao3downloader uses 'category'
                "relationships": metadata.get("pairing", ""),  # ao3downloader uses 'pairing'
                "characters": "",  # Not available from get_work_metadata_from_work
                "additional_tags": "",  # Not available from get_work_metadata_from_work
                "language": metadata.get("language", ""),
                "chapters_current": chapters_current,
                "chapters_max": chapters_max,
                "status": status,
                "published_at": published_at,
                "updated_at": updated_at,
                "summary_html": "",  # Not available from get_work_metadata_from_work
                "total_word_count": words,
                "metadata_source": "scrape",
            }
            
            return result
    
    # If using provided repo, continue with metadata extraction
    # Check for deleted works
    if parse_soup.is_deleted(soup):
        raise ValueError(f"Work {work_id} has been deleted")
    
    # Check for locked works (would need login to access)
    if parse_soup.is_locked(soup):
        # If repo was provided, assume login was already done
        raise ValueError(f"Work {work_id} is locked and could not be accessed")
    
    # Handle explicit content warning (proceed through it)
    if parse_soup.is_explicit(soup):
        proceed_url = parse_soup.get_proceed_link(soup)
        soup = repo.get_soup(proceed_url)
    
    # Extract metadata
    metadata = parse_soup.get_work_metadata_from_work(soup, normalized_url)
    
    # Parse chapters
    chapters_current, chapters_max = parse_chapters(metadata.get("chapters", ""))
    
    # Parse word count
    words = parse_words(metadata.get("words", ""))
    
    # Determine status (complete vs in-progress)
    # AO3 doesn't always provide this directly, but we can infer from chapters
    status = None
    if chapters_max is not None and chapters_current is not None:
        status = "complete" if chapters_current >= chapters_max else "in-progress"
    elif chapters_current is not None and chapters_max is None:
        # If we have current but no max, assume in-progress
        status = "in-progress"
    
    # Parse dates
    published_at = parse_date(metadata.get("published", ""))
    updated_at = parse_date(metadata.get("updated", ""))
    
    # Map ao3downloader metadata to our database format
    result = {
        "ao3_id": work_id,
        "title": metadata.get("title", ""),
        "author": metadata.get("author", ""),
        "url": normalized_url,
        "fandoms": metadata.get("fandom", ""),  # ao3downloader uses 'fandom' (singular)
        "rating": metadata.get("rating", ""),
        "archive_warnings": metadata.get("warning", ""),  # ao3downloader uses 'warning'
        "categories": metadata.get("category", ""),  # ao3downloader uses 'category'
        "relationships": metadata.get("pairing", ""),  # ao3downloader uses 'pairing'
        "characters": "",  # Not available from get_work_metadata_from_work
        "additional_tags": "",  # Not available from get_work_metadata_from_work
        "language": metadata.get("language", ""),
        "chapters_current": chapters_current,
        "chapters_max": chapters_max,
        "status": status,
        "published_at": published_at,
        "updated_at": updated_at,
        "summary_html": "",  # Not available from get_work_metadata_from_work
        "total_word_count": words,
        "metadata_source": "scrape",
    }
    
    return result

