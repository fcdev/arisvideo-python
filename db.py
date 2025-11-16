"""
Database connection and operations for ArisVideo.

This module handles PostgreSQL database connections and provides
functions to update video generation status in the shared database
used by both the Python service and Next.js frontend.
"""

import os
from datetime import datetime
from typing import Optional
from databases import Database
from dotenv import load_dotenv

load_dotenv()

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

database = Database(DATABASE_URL)


async def connect_db():
    """Connect to the database."""
    await database.connect()
    print("Database connected successfully")


async def disconnect_db():
    """Disconnect from the database."""
    await database.disconnect()
    print("Database disconnected")


async def create_video_record(
    video_id: str,
    user_id: Optional[str] = None,
    prompt: Optional[str] = None
) -> None:
    """
    Create a new Video record in the database.

    Args:
        video_id: Unique identifier for the video
        user_id: Optional user ID if authenticated
        prompt: The prompt used to generate the video
    """
    query = """
        INSERT INTO videos (id, video_id, user_id, prompt, status, created_at, updated_at)
        VALUES (:id, :video_id, :user_id, :prompt, :status, :created_at, :updated_at)
        ON CONFLICT (video_id) DO NOTHING
    """
    values = {
        "id": video_id,  # Use same UUID for both id and videoId
        "video_id": video_id,
        "user_id": user_id,
        "prompt": prompt,
        "status": "pending",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    await database.execute(query=query, values=values)


async def update_video_status(
    video_id: str,
    status: str,
    step: int,
    step_message: str,
    error: Optional[str] = None,
    video_url: Optional[str] = None,
    subtitle_path: Optional[str] = None,
    duration: Optional[float] = None,
) -> None:
    """
    Update video status in the database.

    Updates the Video table with current status and creates a VideoStatus
    record for the current step.

    Args:
        video_id: The video ID to update
        status: Current status (pending, processing, completed, failed)
        step: Current step number (0-4)
        step_message: Description of current step
        error: Error message if status is failed
        video_url: URL to the generated video file
        subtitle_path: Path to subtitle file if generated
        duration: Video duration in seconds
    """
    # Update Video table
    update_query = """
        UPDATE videos
        SET status = :status,
            video_url = COALESCE(:video_url, video_url),
            subtitle_path = COALESCE(:subtitle_path, subtitle_path),
            duration = COALESCE(:duration, duration),
            updated_at = :updated_at
        WHERE video_id = :video_id
    """
    update_values = {
        "video_id": video_id,
        "status": status,
        "video_url": video_url,
        "subtitle_path": subtitle_path,
        "duration": duration,
        "updated_at": datetime.utcnow(),
    }
    await database.execute(query=update_query, values=update_values)

    # Insert VideoStatus record for this step
    # Use INSERT ... ON CONFLICT to handle race conditions
    status_query = """
        INSERT INTO video_statuses (id, video_id, step, message, created_at)
        VALUES (gen_random_uuid(), :video_id, :step, :message, :created_at)
        ON CONFLICT (video_id, step) DO UPDATE
        SET message = EXCLUDED.message,
            created_at = EXCLUDED.created_at
    """
    status_values = {
        "video_id": video_id,
        "step": step,
        "message": step_message,
        "created_at": datetime.utcnow(),
    }
    await database.execute(query=status_query, values=status_values)


async def get_video_status(video_id: str) -> Optional[dict]:
    """
    Get the current status of a video from the database.

    Args:
        video_id: The video ID to query

    Returns:
        Dictionary with video status or None if not found
    """
    query = """
        SELECT
            v.id,
            v.video_id,
            v.status,
            v.video_url,
            v.subtitle_path,
            v.duration,
            v.created_at,
            v.updated_at
        FROM videos v
        WHERE v.video_id = :video_id
    """
    result = await database.fetch_one(query=query, values={"video_id": video_id})

    if not result:
        return None

    # Get the latest status message
    status_query = """
        SELECT step, message, created_at
        FROM video_statuses
        WHERE video_id = :video_id
        ORDER BY step DESC
        LIMIT 1
    """
    status_result = await database.fetch_one(
        query=status_query,
        values={"video_id": video_id}
    )

    return {
        "video_id": result["video_id"],
        "status": result["status"],
        "step": status_result["step"] if status_result else 0,
        "message": status_result["message"] if status_result else "",
        "video_url": result["video_url"],
        "subtitle_path": result["subtitle_path"],
        "duration": result["duration"],
        "created_at": result["created_at"],
        "updated_at": result["updated_at"],
    }
