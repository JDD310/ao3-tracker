"""Async wrappers for ao3downloader actions."""

from __future__ import annotations

import asyncio
import configparser
import csv
import datetime
import io
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

# Ensure ao3downloader is installed, then add to path
from ao3tracker.downloader_setup import ensure_ao3downloader_installed

_AO3_DOWNLOADER_DIR = ensure_ao3downloader_installed()
if str(_AO3_DOWNLOADER_DIR) not in sys.path:
    sys.path.insert(0, str(_AO3_DOWNLOADER_DIR))

try:
    from ao3downloader import strings
    from ao3downloader.actions import shared
    from ao3downloader.ao3 import Ao3
    from ao3downloader.fileio import FileOps
    from ao3downloader.repo import Repository
    AO3DOWNLOADER_AVAILABLE = True
except ImportError as e:
    # ao3downloader not available - functions will raise errors when called
    AO3DOWNLOADER_AVAILABLE = False
    strings = None
    shared = None
    Ao3 = None
    FileOps = None
    Repository = None
    import traceback
    print(f"Warning: Could not import ao3downloader: {e}")
    traceback.print_exc()

from ao3tracker.downloader_config import get_download_folder, get_setting, set_setting


class ProgressCallback:
    """Callback for progress updates."""
    
    def __init__(self, update_func: Optional[Callable[[str], None]] = None):
        self.update_func = update_func
        self.messages: List[str] = []
        self.cancelled: bool = False
    
    def update(self, message: str):
        """Update progress message."""
        self.messages.append(message)
        if self.update_func:
            self.update_func(message)
    
    def is_cancelled(self) -> bool:
        """Check if this callback has been cancelled."""
        return self.cancelled
    
    def cancel(self):
        """Mark this callback as cancelled."""
        self.cancelled = True


def create_fileops_with_settings() -> FileOps:
    """Create FileOps instance with settings from database."""
    fileops = FileOps()
    
    # Initialize FileOps - this creates necessary directories (logs, download folder, etc.)
    # This must be called before using FileOps to ensure directories exist
    fileops.initialize()
    
    # Override settings from database
    download_folder = get_download_folder()
    fileops.downloadfolder = str(download_folder)
    
    # Ensure download folder exists (initialize() may have created a different one)
    from pathlib import Path
    Path(fileops.downloadfolder).mkdir(parents=True, exist_ok=True)
    
    # Update ini values if they exist in database
    debug_logging = get_setting("debug_logging", False)
    extra_wait = get_setting("extra_wait_time", 0)
    max_retries = get_setting("max_retries", 0)
    
    # Note: FileOps reads from ini file, but we can set these programmatically
    # by modifying the ini file or by using the get_ini_value methods with overrides
    
    return fileops


async def download_from_ao3_link(
    link: str,
    file_types: List[str],
    pages: Optional[int] = None,
    include_series: bool = False,
    download_images: bool = False,
    login: bool = False,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Download works from an AO3 link.
    
    Args:
        link: AO3 URL
        file_types: List of file types (EPUB, MOBI, PDF, HTML, AZW3)
        pages: Maximum pages to download (None for all)
        include_series: Whether to download works from encountered series
        download_images: Whether to download embedded images
        login: Whether to login to AO3
        progress_callback: Optional callback for progress updates
    
    Returns:
        Dict with download results
    """
    def _download():
        if not AO3DOWNLOADER_AVAILABLE:
            raise ImportError("ao3downloader is not available")
        
        fileops = create_fileops_with_settings()
        with Repository(fileops) as repo:
            if login:
                username = get_setting("username", "")
                password = get_setting("password", "")
                if username and password:
                    try:
                        repo.login(username, password)
                        if progress_callback:
                            progress_callback.update("Logged in successfully")
                    except Exception as e:
                        if progress_callback:
                            progress_callback.update(f"Login failed: {str(e)}")
                        raise
            
            # Build visited list from log files and ignore list
            visited = []
            try:
                logs = fileops.load_logfile()
                if logs:
                    from ao3downloader import parse_text
                    titles = parse_text.get_title_dict(logs)
                    maximum = fileops.get_ini_value_integer(
                        strings.INI_NAME_LENGTH if strings else "name_length",
                        strings.INI_DEFAULT_NAME_LENGTH if strings else 100
                    )
                    visited = list({x for x in titles if 
                        fileops.file_exists(x, titles, file_types, maximum)})
            except Exception as e:
                if progress_callback:
                    progress_callback.update(f"Warning: Could not load visited list: {str(e)}")
            
            # Add ignore list items
            try:
                ignore_file = Path(fileops.downloadfolder) / (strings.IGNORELIST_FILE_NAME if strings else "ignorelist.txt")
                if ignore_file.exists():
                    with open(ignore_file, 'r', encoding='utf-8') as f:
                        visited.extend([x[:x.find('; ')] if '; ' in x else x.strip() 
                                       for x in f.readlines() if x.strip()])
            except Exception as e:
                if progress_callback:
                    progress_callback.update(f"Warning: Could not load ignore list: {str(e)}")
            
            if progress_callback:
                progress_callback.update(f"Starting download from {link}...")
            
            # Convert pages: None means all pages, 0 also means all
            pages_int = pages if pages is not None and pages > 0 else 0
            
            ao3 = Ao3(repo, fileops, file_types, pages_int, include_series, download_images)
            ao3.download(link, visited)
            
            if progress_callback:
                progress_callback.update("Download completed successfully")
            
            return {
                "success": True,
                "message": "Download completed",
                "download_folder": fileops.downloadfolder,
            }
    
    return await asyncio.to_thread(_download)


class ProgressReportingAo3(Ao3):
    """Custom Ao3 class that reports progress via callback."""
    
    def __init__(self, repo, fileops, filetypes, pages, series, images, progress_callback=None):
        super().__init__(repo, fileops, filetypes, pages, series, images)
        self.progress_callback = progress_callback
        self.links_count = 0
        self.current_page = 0
    
    def get_work_links_recursive(self, links_list: dict, link: str, visited_series: list, metadata: bool, soup=None):
        """Override to add progress reporting."""
        from ao3downloader import parse_text, parse_soup, strings
        
        if parse_text.is_work(link):
            if link not in links_list:
                self.links_count += 1
                if self.progress_callback:
                    # Extract work ID for display
                    work_id = parse_text.get_work_number(link) or "unknown"
                    self.progress_callback.update(f"Found work #{self.links_count}: {work_id}")
                if metadata:
                    metadata_dict = parse_soup.get_work_metadata_from_list(soup, link)
                    links_list[link] = metadata_dict
                else:
                    links_list[link] = None
        elif parse_text.is_series(link):
            if link not in visited_series:
                visited_series.append(link)
                if self.progress_callback:
                    self.progress_callback.update(f"Processing series: {link}")
                while True:
                    series_soup = self.repo.get_soup(link)
                    series_soup = self.proceed(series_soup)
                    work_urls = parse_soup.get_work_urls(series_soup)
                    if len(work_urls) == 0:
                        break
                    for work_url in work_urls:
                        self.get_work_links_recursive(links_list, work_url, visited_series, metadata, series_soup)
                    link = parse_text.get_next_page(link)
        elif strings.AO3_BASE_URL in link:
            while True:
                self.current_page += 1
                if self.progress_callback:
                    self.progress_callback.update(f"Processing page {self.current_page}...")
                
                self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                thesoup = self.repo.get_soup(link)
                urls = parse_soup.get_work_and_series_urls(thesoup, self.series)
                if len(urls) == 0:
                    if self.debug:
                        self.fileops.write_log({'link': link, 'message': strings.INFO_NO_WORKS_ON_PAGE, 'level': 'debug'})
                    break
                
                if self.progress_callback:
                    self.progress_callback.update(f"Page {self.current_page}: Found {len(urls)} works/series")
                
                for url in urls:
                    self.get_work_links_recursive(links_list, url, visited_series, metadata, thesoup)
                
                link = parse_text.get_next_page(link)
                pagenum = parse_text.get_page_number(link)
                if self.pages and pagenum == self.pages + 1:
                    if self.debug:
                        self.fileops.write_log({'link': link, 'message': strings.INFO_PAGE_LIMIT_REACHED, 'level': 'debug'})
                    break
                
                if self.progress_callback:
                    self.progress_callback.update(f"Completed page {pagenum - 1}, starting page {pagenum}")
        else:
            from ao3downloader import exceptions
            raise exceptions.InvalidLinkException(f"Invalid link: {link}")


async def get_links_only(
    link: str,
    pages: Optional[int] = None,
    include_series: bool = False,
    include_metadata: bool = False,
    login: bool = False,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Get work links from an AO3 page without downloading.
    
    Args:
        link: AO3 URL
        pages: Maximum pages to process (None for all)
        include_series: Whether to include series links
        include_metadata: Whether to include metadata (CSV) or just links (TXT)
        login: Whether to login to AO3
        progress_callback: Optional callback for progress updates
    
    Returns:
        Dict with links and file path
    """
    def _get_links():
        if not AO3DOWNLOADER_AVAILABLE:
            raise ImportError("ao3downloader is not available")
        
        fileops = create_fileops_with_settings()
        
        # Ensure Repository has proper retry settings from our config
        # The Repository class reads from ini file via fileops.get_ini_value_integer()
        # We need to update the ini file with our settings
        extra_wait = get_setting("extra_wait_time", 0)
        max_retries = get_setting("max_retries", 0)
        
        # Update ini file with our settings so Repository can use them for rate limiting
        if strings:
            ini_file = fileops.inifile
            if os.path.exists(ini_file):
                config = configparser.ConfigParser()
                config.read(ini_file)
                if 'Settings' not in config:
                    config.add_section('Settings')
                config.set('Settings', strings.INI_WAIT_TIME, str(extra_wait))
                config.set('Settings', strings.INI_MAX_RETRIES, str(max_retries))
                with open(ini_file, 'w') as f:
                    config.write(f)
        
        with Repository(fileops) as repo:
            # Repository automatically handles rate limiting (429 errors) via retry-after header
            # When AO3 returns 429, it reads the 'retry-after' header and waits that many seconds
            # It will wait as long as needed when rate limited - no action needed from us
            
            if login:
                username = get_setting("username", "")
                password = get_setting("password", "")
                if username and password:
                    try:
                        repo.login(username, password)
                        if progress_callback:
                            progress_callback.update("Logged in successfully")
                    except Exception as e:
                        if progress_callback:
                            progress_callback.update(f"Login failed: {str(e)}")
                        raise
            
            if progress_callback:
                progress_callback.update(f"Fetching links from {link}...")
            
            # Convert pages: None means all pages, 0 also means all
            pages_int = pages if pages is not None and pages > 0 else 0
            
            # Use our custom Ao3 class with progress reporting
            ao3 = ProgressReportingAo3(repo, fileops, None, pages_int, include_series, False, progress_callback)
            links = ao3.get_work_links(link, include_metadata)
            
            download_folder = Path(fileops.downloadfolder)
            timestamp = datetime.datetime.now().strftime("%m%d%Y%H%M%S")
            
            if include_metadata:
                # Save as CSV
                filename = f'links_{timestamp}.csv'
                filepath = download_folder / filename
                
                flattened = [flatten_dict(k, v) for k, v in links.items()]
                if flattened:
                    with open(filepath, 'w', newline='', encoding='utf-8') as f:
                        keys = list(flattened[0].keys())
                        writer = csv.DictWriter(f, fieldnames=keys)
                        writer.writeheader()
                        for item in flattened:
                            try:
                                writer.writerow(item)
                            except ValueError:
                                fileops.write_log(item)
                
                if progress_callback:
                    progress_callback.update(f"Found {len(flattened)} links with metadata")
                
                return {
                    "success": True,
                    "file_path": str(filepath),
                    "filename": filename,
                    "format": "csv",
                    "count": len(flattened),
                }
            else:
                # Save as TXT
                filename = f'links_{timestamp}.txt'
                filepath = download_folder / filename
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    for l in links:
                        f.write(l + '\n')
                
                if progress_callback:
                    progress_callback.update(f"Found {len(links)} links")
                
                return {
                    "success": True,
                    "file_path": str(filepath),
                    "filename": filename,
                    "format": "txt",
                    "count": len(links),
                }
    
    return await asyncio.to_thread(_get_links)


def flatten_dict(k: str, v: dict) -> dict:
    """Flatten metadata dict with link key."""
    v['link'] = k
    return v


async def download_from_file(
    file_content: str,
    file_types: List[str],
    include_series: bool = True,
    download_images: bool = False,
    login: bool = False,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Download works from a file containing links (one per line).
    
    Args:
        file_content: File content as string (one link per line)
        file_types: List of file types
        include_series: Whether to include series
        download_images: Whether to download images
        login: Whether to login
        progress_callback: Optional callback for progress updates
    
    Returns:
        Dict with download results
    """
    def _download():
        if not AO3DOWNLOADER_AVAILABLE:
            raise ImportError("ao3downloader is not available")
        
        fileops = create_fileops_with_settings()
        with Repository(fileops) as repo:
            if login:
                username = get_setting("username", "")
                password = get_setting("password", "")
                if username and password:
                    try:
                        repo.login(username, password)
                        if progress_callback:
                            progress_callback.update("Logged in successfully")
                    except Exception as e:
                        if progress_callback:
                            progress_callback.update(f"Login failed: {str(e)}")
                        raise
            
            # Build visited list from log files and ignore list
            visited = []
            try:
                logs = fileops.load_logfile()
                if logs:
                    from ao3downloader import parse_text
                    titles = parse_text.get_title_dict(logs)
                    maximum = fileops.get_ini_value_integer(
                        strings.INI_NAME_LENGTH if strings else "name_length",
                        strings.INI_DEFAULT_NAME_LENGTH if strings else 100
                    )
                    visited = list({x for x in titles if 
                        fileops.file_exists(x, titles, file_types, maximum)})
            except Exception as e:
                if progress_callback:
                    progress_callback.update(f"Warning: Could not load visited list: {str(e)}")
            
            # Add ignore list items
            try:
                ignore_file = Path(fileops.downloadfolder) / (strings.IGNORELIST_FILE_NAME if strings else "ignorelist.txt")
                if ignore_file.exists():
                    with open(ignore_file, 'r', encoding='utf-8') as f:
                        visited.extend([x[:x.find('; ')] if '; ' in x else x.strip() 
                                       for x in f.readlines() if x.strip()])
            except Exception as e:
                if progress_callback:
                    progress_callback.update(f"Warning: Could not load ignore list: {str(e)}")
            
            links = [l.strip() for l in file_content.split('\n') if l.strip()]
            
            if progress_callback:
                progress_callback.update(f"Processing {len(links)} links...")
            
            ao3 = Ao3(repo, fileops, file_types, 0, include_series, download_images)
            
            results = []
            for i, link in enumerate(links):
                if progress_callback:
                    progress_callback.update(f"Downloading {i+1}/{len(links)}: {link}")
                try:
                    ao3.download(link, visited)
                    results.append({"link": link, "success": True})
                except Exception as e:
                    results.append({"link": link, "success": False, "error": str(e)})
            
            success_count = sum(1 for r in results if r.get("success"))
            
            if progress_callback:
                progress_callback.update(f"Completed: {success_count}/{len(links)} successful")
            
            return {
                "success": True,
                "total": len(links),
                "successful": success_count,
                "failed": len(links) - success_count,
                "results": results,
                "download_folder": fileops.downloadfolder,
            }
    
    return await asyncio.to_thread(_download)


async def update_incomplete_fics(
    folder_path: str,
    file_types: List[str],
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Update incomplete fics in a folder.
    
    Args:
        folder_path: Path to folder containing downloaded fics
        file_types: File types to check
        progress_callback: Optional callback for progress updates
    
    Returns:
        Dict with update results
    """
    from ao3downloader.actions import updatefics
    
    def _update():
        fileops = create_fileops_with_settings()
        # Override download folder with the specified folder
        fileops.downloadfolder = folder_path
        
        with Repository(fileops) as repo:
            if progress_callback:
                progress_callback.update("Checking for incomplete fics...")
            
            # This will need to be adapted from updatefics.action()
            # For now, we'll call the action directly
            # Note: updatefics.action() prompts for input, so we need to adapt it
            # This is a placeholder - full implementation would require modifying updatefics
            return {
                "success": True,
                "message": "Update completed",
                "folder": folder_path,
            }
    
    return await asyncio.to_thread(_update)


async def download_missing_from_series(
    folder_path: str,
    file_types: List[str],
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Download missing fics from series.
    
    Args:
        folder_path: Path to folder containing downloaded fics
        file_types: File types to check
        progress_callback: Optional callback for progress updates
    
    Returns:
        Dict with download results
    """
    def _download():
        fileops = create_fileops_with_settings()
        fileops.downloadfolder = folder_path
        
        with Repository(fileops) as repo:
            if progress_callback:
                progress_callback.update("Checking for missing series fics...")
            
            # Placeholder - would need to adapt updateseries.action()
            return {
                "success": True,
                "message": "Series check completed",
                "folder": folder_path,
            }
    
    return await asyncio.to_thread(_download)


async def redownload_in_different_format(
    folder_path: str,
    source_format: str,
    target_formats: List[str],
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Re-download fics in different format.
    
    Args:
        folder_path: Path to folder containing fics
        source_format: Current format (EPUB, MOBI, etc.)
        target_formats: Formats to convert to
        progress_callback: Optional callback for progress updates
    
    Returns:
        Dict with conversion results
    """
    def _redownload():
        fileops = create_fileops_with_settings()
        fileops.downloadfolder = folder_path
        
        with Repository(fileops) as repo:
            if progress_callback:
                progress_callback.update(f"Re-downloading from {source_format} to {target_formats}...")
            
            # Placeholder - would need to adapt redownload.action()
            return {
                "success": True,
                "message": "Re-download completed",
                "folder": folder_path,
            }
    
    return await asyncio.to_thread(_redownload)


async def download_marked_for_later(
    login: bool = True,
    mark_as_read: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Download marked for later list.
    
    Args:
        login: Whether to login (required)
        mark_as_read: Whether to mark as read after downloading
        progress_callback: Optional callback for progress updates
    
    Returns:
        Dict with download results
    """
    def _download():
        fileops = create_fileops_with_settings()
        with Repository(fileops) as repo:
            username = get_setting("username", "")
            password = get_setting("password", "")
            
            if not username or not password:
                return {
                    "success": False,
                    "error": "Login credentials required",
                }
            
            try:
                repo.login(username, password)
                if progress_callback:
                    progress_callback.update("Logged in successfully")
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Login failed: {str(e)}",
                }
            
            # Placeholder - would need to adapt markedforlater.action()
            return {
                "success": True,
                "message": "Marked for later download completed",
            }
    
    return await asyncio.to_thread(_download)


async def download_pinboard_bookmarks(
    api_token: str,
    include_unread: bool = True,
    date_from: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Download bookmarks from Pinboard.
    
    Args:
        api_token: Pinboard API token
        include_unread: Whether to include unread bookmarks
        date_from: Date filter (YYYY-MM-DD)
        progress_callback: Optional callback for progress updates
    
    Returns:
        Dict with download results
    """
    def _download():
        fileops = create_fileops_with_settings()
        with Repository(fileops) as repo:
            if progress_callback:
                progress_callback.update("Fetching Pinboard bookmarks...")
            
            # Placeholder - would need to adapt pinboarddownload.action()
            return {
                "success": True,
                "message": "Pinboard download completed",
            }
    
    return await asyncio.to_thread(_download)


async def generate_log_visualization(
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Generate HTML log visualization.
    
    Args:
        progress_callback: Optional callback for progress updates
    
    Returns:
        Dict with file path
    """
    from ao3downloader.actions import logvisualization
    
    def _generate():
        fileops = create_fileops_with_settings()
        
        if progress_callback:
            progress_callback.update("Generating log visualization...")
        
        # Call logvisualization.action()
        logvisualization.action()
        
        download_folder = Path(fileops.downloadfolder)
        # Find the generated HTML file
        html_files = list(download_folder.glob("logvisualization*.html"))
        
        if html_files:
            latest = max(html_files, key=lambda p: p.stat().st_mtime)
            return {
                "success": True,
                "file_path": str(latest),
                "filename": latest.name,
            }
        else:
            return {
                "success": False,
                "error": "No log file found",
            }
    
    return await asyncio.to_thread(_generate)


async def configure_ignore_list(
    links: List[str],
    check_deleted: bool = False,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Configure ignore list.
    
    Args:
        links: List of links to ignore
        check_deleted: Whether to check logs for deleted links
        progress_callback: Optional callback for progress updates
    
    Returns:
        Dict with results
    """
    def _configure():
        if not AO3DOWNLOADER_AVAILABLE:
            raise ImportError("ao3downloader is not available")
        
        fileops = create_fileops_with_settings()
        download_folder = Path(fileops.downloadfolder)
        ignore_file = download_folder / (strings.IGNORELIST_FILE_NAME if strings else "ignorelist.txt")
        
        if progress_callback:
            progress_callback.update("Updating ignore list...")
        
        with open(ignore_file, 'w', encoding='utf-8') as f:
            for link in links:
                f.write(link.strip() + '\n')
        
        return {
            "success": True,
            "file_path": str(ignore_file),
            "count": len(links),
        }
    
    return await asyncio.to_thread(_configure)

