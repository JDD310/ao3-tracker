# AO3 Subscription Tracker

A self-hosted web application for tracking and managing your Archive of Our Own (AO3) subscription updates. This tool parses AO3 subscription emails from Gmail/IMAP, stores update information in a local database, and provides a beautiful web interface to browse your tracked works, view update history, and monitor statistics.

## Features

### Core Functionality
- **Email Ingestion**: Automatically parses AO3 subscription emails from Gmail (via Gmail API) or IMAP
- **Update Tracking**: Stores all update information including chapter labels, word counts, and timestamps
- **Work Management**: Tracks works with metadata including title, author, fandoms, ratings, and more
- **Update History**: View complete update history for each work with detailed statistics

### Web Interface
- **Dashboard**: View recent updates across all works with filtering and pagination
- **Works List**: Browse all tracked works with search and filtering capabilities
- **Work Details**: Detailed view for each work showing:
  - Complete update history
  - Word count trends over time
  - Average days between updates
  - Chapter progression tracking
  - Read/unread status
- **Search**: Search works by title or author
- **Status Page**: View system statistics and health information

### Additional Features
- **Work Scraping**: Manually scrape and store metadata from AO3 work URLs
- **Statistics**: Calculate and display analytics including:
  - Average words per chapter
  - Update frequency patterns
  - Word count growth over time
- **Read/Unread Tracking**: Mark updates as read to track your reading progress
- **AO3 Downloader Integration**: Full integration with ao3downloader for downloading works:
  - Download works from AO3 links (single works, series, or listing pages)
  - Extract work links only (without downloading)
  - Download from file containing multiple links
  - Update incomplete fics automatically
  - Download missing works from series
  - Re-download works in different formats
  - Download from "Marked for Later" list
  - Download from Pinboard bookmarks
  - Generate log visualizations
  - Configure ignore lists
  - Background job processing with progress tracking

## Installation

### Prerequisites
- Python 3.10 or higher
- Git (for automatic ao3downloader installation)
- Gmail account with AO3 subscription emails, or IMAP access to your email
- (Optional) Google API credentials for Gmail API access

### ao3downloader Setup
The application requires `ao3downloader` to be present in the project root directory. The application will automatically clone it from GitHub if it's not found.

**Location**: Place the `ao3downloader` directory at the project root:
```
ao3-tracker/
├── src/
├── templates/
├── ao3downloader/    ← Should be here
├── requirements.txt
└── README.md
```

**Automatic Installation**: The application will automatically clone `ao3downloader` from https://github.com/nianeyna/ao3downloader if it's not found. Make sure you have `git` installed.

**Manual Installation** (if automatic fails):
```bash
cd /path/to/ao3-tracker
git clone https://github.com/nianeyna/ao3downloader.git
```

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd ao3-tracker
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up Gmail API (Optional - for Gmail access)**
   - Follow the [Gmail API Python Quickstart](https://developers.google.com/gmail/api/quickstart/python)
   - Place `credentials.json` in the project root
   - Run the application once to generate `token.json` through OAuth flow

5. **Set up IMAP (Alternative to Gmail API)**
   - Configure IMAP credentials in your environment or configuration
   - The application supports standard IMAP email access

6. **Initialize the database**
   - The database will be automatically created on first run
   - Database file: `ao3_tracker.db` (SQLite)

## Usage

### Running the Application

Start the web server:
```bash
uvicorn src.ao3tracker.main:app --reload
```

The application will be available at `http://localhost:8000`

### Ingesting Emails

To process AO3 subscription emails:

1. **Using Gmail API**: The application will automatically authenticate and fetch emails
2. **Using IMAP**: Configure your IMAP settings and run the ingestion script

### Web Interface

- **Home (`/`)**: View recent updates
- **Works (`/works`)**: Browse all tracked works
- **Work Detail (`/works/{id}`)**: View detailed information about a specific work
- **Search (`/search`)**: Search for works by title or author
- **Status (`/status`)**: View system statistics
- **Scrape Works (`/works/scrape`)**: Manually scrape metadata from AO3 URLs
- **Downloader (`/downloader`)**: Full-featured interface for downloading works from AO3:
  - Download from AO3 links with customizable options
  - Extract links only (with optional metadata export)
  - Download from file containing multiple links
  - Update incomplete fics
  - Download missing works from series
  - Re-download in different formats
  - Download from "Marked for Later" list
  - Download from Pinboard bookmarks
  - Generate log visualizations
  - Configure ignore lists
  - View job history and progress

### API Endpoints

The application provides a REST API for programmatic access:

**Core API:**
- `GET /api/v1/updates` - List updates with pagination and filtering
- `GET /api/v1/works` - List works with pagination
- `GET /api/v1/works/{id}` - Get work details with updates
- `POST /api/v1/works/{id}/mark-read` - Mark all updates for a work as read

**Downloader API:**
- `POST /api/v1/downloader/jobs/download-from-link` - Create download job from AO3 link
- `POST /api/v1/downloader/jobs/get-links` - Create job to extract links only
- `POST /api/v1/downloader/jobs/download-from-file` - Create download job from file
- `POST /api/v1/downloader/jobs/update-incomplete` - Create job to update incomplete fics
- `POST /api/v1/downloader/jobs/download-missing-series` - Create job to download missing series works
- `POST /api/v1/downloader/jobs/redownload` - Create job to re-download in different format
- `POST /api/v1/downloader/jobs/marked-for-later` - Create job to download marked for later
- `POST /api/v1/downloader/jobs/pinboard` - Create job to download Pinboard bookmarks
- `POST /api/v1/downloader/jobs/log-visualization` - Create job to generate log visualization
- `POST /api/v1/downloader/jobs/ignore-list` - Create job to configure ignore list
- `GET /api/v1/downloader/jobs` - List all download jobs
- `GET /api/v1/downloader/jobs/{job_id}` - Get job status
- `GET /api/v1/downloader/jobs/{job_id}/progress` - Get job progress updates
- `GET /api/v1/downloader/settings` - Get downloader settings
- `POST /api/v1/downloader/settings` - Update downloader settings

See the FastAPI automatic documentation at `http://localhost:8000/docs` for full API details.

## Project Structure

```
ao3-tracker/
├── src/
│   └── ao3tracker/
│       ├── main.py                    # FastAPI application entry point
│       ├── db.py                      # Database operations
│       ├── models.py                  # Pydantic models
│       ├── routes_html.py             # HTML route handlers
│       ├── routes_api.py              # API route handlers
│       ├── routes_downloader.py        # Downloader API routes
│       ├── routes_downloader_html.py  # Downloader HTML routes
│       ├── ingest_imap.py             # Email ingestion logic
│       ├── imap_client.py             # IMAP connection handling
│       ├── scrape_works.py            # AO3 work scraping
│       ├── ao3_downloader_adapter.py  # Integration with ao3downloader
│       ├── downloader_service.py      # Downloader job management
│       ├── downloader_config.py       # Downloader configuration
│       ├── downloader_wrappers.py     # Async wrappers for ao3downloader
│       └── utils.py                   # Utility functions
├── templates/                         # Jinja2 HTML templates
│   ├── downloader.html               # Downloader interface page
│   └── downloader_job.html           # Job status page
├── static/                            # Static files (CSS, JS)
├── requirements.txt                   # Python dependencies
├── ao3_tracker.db                    # SQLite database (created on first run)
└── README.md                          # This file
```

## Configuration

### Database
The application uses SQLite by default. The database file (`ao3_tracker.db`) is created automatically in the project root.

### Email Access
- **Gmail API**: Requires `credentials.json` and `token.json` files
- **IMAP**: Configure via environment variables or configuration file

### Downloader Configuration
The downloader can be configured through the web interface at `/downloader` or via the API. Settings include:
- Download folder path
- Default file types (EPUB, MOBI, PDF, HTML, AZW3)
- AO3 login credentials (optional, for accessing locked works)
- Pinboard API token (optional, for Pinboard integration)
- Debug logging
- Wait times and retry settings

## Development

### Running in Development Mode
```bash
uvicorn src.ao3tracker.main:app --reload --host 0.0.0.0 --port 8000
```

### Database Schema
The application uses SQLite with the following main tables:
- `works`: Stores work metadata
- `updates`: Stores individual update records
- `processed_messages`: Tracks processed emails to avoid duplicates
- `download_jobs`: Tracks download jobs and their status
- `download_settings`: Stores downloader configuration settings

## License

This project is licensed under the terms specified in the LICENSE file. Please note that this project integrates with `ao3downloader`, which is licensed under GPL-3.0. See `NOTICES` for full attribution details.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## Acknowledgments

This project integrates with and uses code from several open-source projects. See `NOTICES` for a complete list of acknowledgments and licenses.

## Disclaimer

This tool is designed to help you track your AO3 subscriptions through email notifications. It does not scrape AO3 directly and respects AO3's Terms of Service by using only email-based data. The work scraping feature is for metadata only and should be used responsibly.

The downloader integration uses ao3downloader, which respects AO3's rate limits and terms of service. Downloads are performed with appropriate delays and respect for AO3's infrastructure. Please use responsibly and in accordance with AO3's Terms of Service.

## Support

For issues, questions, or contributions, please open an issue on the project repository.

