"""Setup and installation utilities for ao3downloader."""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path


def get_project_root() -> Path:
    """Get the project root directory (where ao3downloader should be placed)."""
    # This file is at: src/ao3tracker/downloader_setup.py
    # Go up 3 levels to reach project root
    return Path(__file__).resolve().parent.parent.parent


def ensure_ao3downloader_installed() -> Path:
    """
    Ensure ao3downloader is installed in the project root.
    If it doesn't exist, clone it from GitHub.
    
    The ao3downloader directory should be placed at:
        <project_root>/ao3downloader/
    
    Returns:
        Path to the ao3downloader directory
    """
    project_root = get_project_root()
    ao3downloader_dir = project_root / "ao3downloader"
    
    # Check if ao3downloader is already installed
    if ao3downloader_dir.exists() and (ao3downloader_dir / "ao3downloader").exists():
        # Already installed
        return ao3downloader_dir
    
    # Try to clone it
    print("ao3downloader not found. Attempting to clone from GitHub...")
    print(f"Target location: {ao3downloader_dir}")
    
    repo_url = "https://github.com/nianeyna/ao3downloader.git"
    
    try:
        result = subprocess.run(
            ["git", "clone", repo_url, str(ao3downloader_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"✓ Successfully cloned ao3downloader to {ao3downloader_dir}")
        return ao3downloader_dir
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or e.stdout or "Unknown error"
        raise RuntimeError(
            f"Failed to clone ao3downloader from GitHub.\n"
            f"Error: {error_msg}\n\n"
            f"Please manually clone it to: {ao3downloader_dir}\n"
            f"Run: git clone {repo_url} {ao3downloader_dir}\n\n"
            f"Or download from: {repo_url}"
        )
    except FileNotFoundError:
        raise RuntimeError(
            "git is not installed. Please install git or manually clone ao3downloader:\n"
            f"  git clone {repo_url} {ao3downloader_dir}\n\n"
            f"Or download the repository manually and place it at: {ao3downloader_dir}"
        )

