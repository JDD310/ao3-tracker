"""Scraping pipeline for fetching and storing work metadata from AO3 URLs."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Dict, Any

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
) -> Dict[str, Any]:
    """
    Scrape metadata from AO3 URLs and store in database.
    
    Args:
        urls: Iterable of AO3 work URLs
        force_rescrape: If True, rescrape even if work exists in DB
    
    Returns:
        Dict with:
            - processed: int (number of URLs processed)
            - inserted: int (number of new works inserted)
            - updated: int (number of existing works updated)
            - errors: list[dict] (list of error dicts with 'url' and 'error' keys)
    """
    conn = get_connection()
    cur = conn.cursor()
    
    stats = {
        "processed": 0,
        "inserted": 0,
        "updated": 0,
        "errors": [],
    }
    
    for url in urls:
        if not url or not url.strip():
            continue
        
        url = url.strip()
        stats["processed"] += 1
        
        try:
            # Normalize URL
            normalized_url = normalize_work_url(url)
            work_id = extract_work_id(normalized_url)
            
            if not work_id:
                raise ValueError(f"Could not extract work ID from URL: {url}")
            
            # Check if work exists
            cur.execute("SELECT id FROM works WHERE ao3_id = ?", (work_id,))
            existing = cur.fetchone()
            
            # Skip if exists and not forcing rescrape
            if existing and not force_rescrape:
                logger.info(f"Skipping work {work_id} (already exists, use force_rescrape=True to update)")
                continue
            
            # Fetch metadata
            logger.info(f"Fetching metadata for work {work_id} from {normalized_url}")
            metadata = fetch_work_metadata_via_ao3_downloader(normalized_url)
            
            # Store in database
            was_existing = existing is not None
            upsert_work_with_metadata(conn, metadata)
            
            if was_existing:
                stats["updated"] += 1
                logger.info(f"Updated work {work_id}: {metadata.get('title', 'Unknown')}")
            else:
                stats["inserted"] += 1
                logger.info(f"Inserted work {work_id}: {metadata.get('title', 'Unknown')}")
        
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error processing {url}: {error_msg}", exc_info=True)
            stats["errors"].append({
                "url": url,
                "error": error_msg,
            })
    
    conn.close()
    return stats

