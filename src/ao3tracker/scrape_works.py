"""Scraping pipeline for fetching and storing work metadata from AO3 URLs."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Callable
from typing import Dict, Any, Optional

from ao3tracker.ao3_downloader_adapter import (
    fetch_work_metadata_via_ao3_downloader,
    normalize_work_url,
    extract_work_id,
)
from ao3tracker.db import get_connection, upsert_work_with_metadata

logger = logging.getLogger(__name__)


def scrape_and_store_works(
    urls: Iterable[str],
    force_rescrape: bool = False,
    login: bool = False,
    username: Optional[str] = None,
    password: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Scrape metadata from AO3 URLs and store in database.
    
    Args:
        urls: Iterable of AO3 work URLs
        force_rescrape: If True, rescrape even if work exists in DB
        login: If True, login to AO3 (required for locked works)
        progress_callback: Optional callback function for progress updates (takes message string)
    
    Returns:
        Dict with:
            - processed: int (number of URLs processed)
            - inserted: int (number of new works inserted)
            - updated: int (number of existing works updated)
            - errors: list[dict] (list of error dicts with 'url' and 'error' keys)
    """
    conn = get_connection()
    cur = conn.cursor()
    
    # Convert urls to list to get count
    url_list = [url.strip() for url in urls if url and url.strip()]
    total_urls = len(url_list)
    
    if progress_callback:
        progress_callback(f"Starting scrape of {total_urls} URL(s)...")
    
    # Create a single Repository instance for all works (much faster!)
    repo = None
    if login:
        from ao3downloader.fileio import FileOps
        from ao3downloader.repo import Repository
        from ao3tracker.downloader_config import get_setting
        
        fileops = FileOps()
        fileops.initialize()
        repo = Repository(fileops)
        repo.__enter__()  # Manually enter context manager
        
        # Get username from settings if not provided
        if not username:
            username = get_setting("username", "")
        
        if not username or not password:
            if repo:
                try:
                    repo.__exit__(None, None, None)
                except:
                    pass
            raise ValueError("Login requested but username and password are required. Please provide them in the request.")
        
        try:
            if progress_callback:
                progress_callback("Logging in to AO3...")
            repo.login(username, password)
            if progress_callback:
                progress_callback("✓ Logged in successfully")
        except Exception as e:
            if repo:
                try:
                    repo.__exit__(None, None, None)
                except:
                    pass
            raise ValueError(f"Login failed: {str(e)}")
        finally:
            # Clear password from memory
            if password:
                password = None
    
    stats = {
        "processed": 0,
        "inserted": 0,
        "updated": 0,
        "errors": [],
    }
    
    try:
        for idx, url in enumerate(url_list, 1):
            if not url or not url.strip():
                continue
            
            stats["processed"] += 1
            
            try:
                # Normalize URL
                normalized_url = normalize_work_url(url)
                work_id = extract_work_id(normalized_url)
                
                if not work_id:
                    raise ValueError(f"Could not extract work ID from URL: {url}")
                
                if progress_callback:
                    progress_callback(f"[{idx}/{total_urls}] Processing work {work_id}...")
                
                # Check if work exists
                cur.execute("SELECT id FROM works WHERE ao3_id = ?", (work_id,))
                existing = cur.fetchone()
                
                # Skip if exists and not forcing rescrape
                if existing and not force_rescrape:
                    logger.info(f"Skipping work {work_id} (already exists, use force_rescrape=True to update)")
                    if progress_callback:
                        progress_callback(f"[{idx}/{total_urls}] Skipped work {work_id} (already exists)")
                    continue
                
                # Fetch metadata
                logger.info(f"Fetching metadata for work {work_id} from {normalized_url} (login: {login})")
                if progress_callback:
                    progress_callback(f"[{idx}/{total_urls}] Fetching metadata for work {work_id}...")
                
                # Pass the repo instance to reuse the same session (much faster!)
                metadata = fetch_work_metadata_via_ao3_downloader(normalized_url, login=login, username=username, password=password, repo=repo)
                
                # Store in database
                was_existing = existing is not None
                upsert_work_with_metadata(conn, metadata)
                
                if was_existing:
                    stats["updated"] += 1
                    title = metadata.get('title', 'Unknown')
                    logger.info(f"Updated work {work_id}: {title}")
                    if progress_callback:
                        progress_callback(f"[{idx}/{total_urls}] ✓ Updated: {title}")
                else:
                    stats["inserted"] += 1
                    title = metadata.get('title', 'Unknown')
                    logger.info(f"Inserted work {work_id}: {title}")
                    if progress_callback:
                        progress_callback(f"[{idx}/{total_urls}] ✓ Inserted: {title}")
            
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error processing {url}: {error_msg}", exc_info=True)
                stats["errors"].append({
                    "url": url,
                    "error": error_msg,
                })
                if progress_callback:
                    progress_callback(f"[{idx}/{total_urls}] ✗ Error: {error_msg}")
    
    finally:
        # Clean up repository if we created one
        if repo:
            try:
                repo.__exit__(None, None, None)
            except:
                pass
    
    if progress_callback:
        progress_callback(f"Completed: {stats['inserted']} inserted, {stats['updated']} updated, {len(stats['errors'])} errors")
    
    conn.close()
    return stats

