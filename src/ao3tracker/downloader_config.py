"""Configuration management for ao3downloader integration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from ao3tracker.db import get_connection


# Default settings
DEFAULT_SETTINGS = {
    "download_folder": str(Path.cwd() / "downloads"),
    "file_types": ["EPUB"],  # Default to EPUB
    "username": "",
    "password": "",  # Should be encrypted in production
    "pinboard_api_token": "",
    "debug_logging": False,
    "extra_wait_time": 0,
    "max_retries": 0,
    "save_password": False,
}


def get_setting(key: str, default: Any = None) -> Any:
    """Get a setting value from database, or return default."""
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT setting_value FROM download_settings WHERE setting_key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    
    if row is None:
        # Return default from DEFAULT_SETTINGS if available
        return DEFAULT_SETTINGS.get(key, default)
    
    value = row["setting_value"]
    if value is None:
        return default
    
    # Try to parse as JSON (for lists, dicts, etc.)
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        # Return as string or boolean
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        return value


def set_setting(key: str, value: Any) -> None:
    """Set a setting value in database."""
    conn = get_connection()
    cur = conn.cursor()
    
    # Convert value to JSON string if it's not a string
    if isinstance(value, (list, dict, bool)):
        value_str = json.dumps(value)
    else:
        value_str = str(value) if value is not None else None
    
    cur.execute("""
        INSERT INTO download_settings (setting_key, setting_value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value = excluded.setting_value,
            updated_at = CURRENT_TIMESTAMP
    """, (key, value_str))
    
    conn.commit()
    conn.close()


def get_all_settings() -> Dict[str, Any]:
    """Get all settings as a dictionary."""
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT setting_key, setting_value FROM download_settings")
    rows = cur.fetchall()
    conn.close()
    
    settings = DEFAULT_SETTINGS.copy()
    for row in rows:
        key = row["setting_key"]
        value = row["setting_value"]
        
        if value is not None:
            try:
                settings[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                if value.lower() in ("true", "false"):
                    settings[key] = value.lower() == "true"
                else:
                    settings[key] = value
    
    return settings


def get_download_folder() -> Path:
    """Get the download folder path, creating it if necessary."""
    folder = get_setting("download_folder", DEFAULT_SETTINGS["download_folder"])
    path = Path(folder)
    path.mkdir(parents=True, exist_ok=True)
    return path


def initialize_default_settings() -> None:
    """Initialize default settings if they don't exist."""
    conn = get_connection()
    cur = conn.cursor()
    
    for key, value in DEFAULT_SETTINGS.items():
        cur.execute("SELECT 1 FROM download_settings WHERE setting_key = ?", (key,))
        if cur.fetchone() is None:
            set_setting(key, value)
    
    conn.close()

