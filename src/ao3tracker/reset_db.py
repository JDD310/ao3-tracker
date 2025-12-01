#!/usr/bin/env python3
"""
Utility script to reset the database or clear processed messages.
"""

from ao3tracker.db import (
    reset_database,
    reset_processed_messages_only,
)


def main():
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--full":
        print("WARNING: This will delete ALL data (works, updates, and processed messages).")
        response = input("Are you sure? Type 'yes' to confirm: ")
        if response.lower() == "yes":
            reset_database()
        else:
            print("Reset cancelled.")
    else:
        print("This will clear only the processed_messages table.")
        print("Your works and updates will remain intact.")
        response = input("Continue? (y/n): ")
        if response.lower() in ("y", "yes"):
            reset_processed_messages_only()
        else:
            print("Reset cancelled.")


if __name__ == "__main__":
    main()

