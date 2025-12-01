from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


def parse_email_date(date_str: str) -> Optional[datetime]:
    """Parse email date string, handling ISO format and other common formats."""
    if not date_str:
        return None
    
    try:
        # Try ISO format first (most common)
        date_str_clean = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(date_str_clean)
    except (ValueError, AttributeError):
        try:
            # Try parsing with email.utils
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str)
        except (ValueError, TypeError, AttributeError):
            return None


def calculate_work_statistics(updates: list, work: dict) -> dict:
    """Calculate statistics about a work based on its updates."""
    stats = {
        "total_updates": len(updates),
        "average_words_per_chapter": None,
        "total_word_count": work.get("total_word_count"),
        "next_expected_release": None,
        "average_days_between_updates": None,
        "word_count_data": [],
    }
    
    if not updates:
        return stats
    
    # Collect word count data for graph (work_word_count over time)
    word_count_data = []
    chapter_word_counts = []
    
    for update in updates:
        if update.get("work_word_count") is not None:
            try:
                # Parse email_date (ISO format)
                email_date = update["email_date"]
                if email_date:
                    word_count_data.append({
                        "date": email_date,
                        "word_count": update["work_word_count"]
                    })
            except (ValueError, TypeError):
                pass
        
        if update.get("chapter_word_count") is not None:
            chapter_word_counts.append(update["chapter_word_count"])
    
    stats["word_count_data"] = word_count_data
    
    # Calculate average words per chapter
    if chapter_word_counts:
        stats["average_words_per_chapter"] = sum(chapter_word_counts) / len(chapter_word_counts)
    
    # Calculate average days between updates and predict next release
    if len(updates) >= 2:
        date_diffs = []
        valid_dates = []
        
        for i in range(1, len(updates)):
            date1_str = updates[i-1]["email_date"]
            date2_str = updates[i]["email_date"]
            
            date1 = parse_email_date(date1_str) if date1_str else None
            date2 = parse_email_date(date2_str) if date2_str else None
            
            if date1 and date2:
                diff = (date2 - date1).days
                if diff > 0:  # Only count positive differences
                    date_diffs.append(diff)
                    valid_dates.append((date1, date2))
        
        if date_diffs:
            avg_days = sum(date_diffs) / len(date_diffs)
            stats["average_days_between_updates"] = round(avg_days, 1)
            
            # Predict next release date based on last update + average days
            if valid_dates:
                last_date = valid_dates[-1][1]
                next_release = last_date + timedelta(days=avg_days)
                stats["next_expected_release"] = next_release.isoformat()
    
    return stats

