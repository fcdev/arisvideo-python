"""
Database-backed status tracking for video generation.

This module provides a simple interface for tracking video generation status
that writes directly to PostgreSQL instead of using in-memory storage.
"""

from typing import Optional
from db import update_video_status, create_video_record


class StatusTracker:
    """
    Database-backed status tracker.

    This class provides the same interface as the old in-memory tracker
    but writes all status updates directly to PostgreSQL.
    """

    async def create(
        self,
        video_id: str,
        initial_message: str = "Initializing",
        user_id: Optional[str] = None,
        prompt: Optional[str] = None
    ) -> None:
        """
        Create a new video status entry in the database.

        Args:
            video_id: Unique identifier for the video
            initial_message: Initial status message
            user_id: Optional user ID if authenticated
            prompt: The prompt used to generate the video
        """
        # Create the Video record
        await create_video_record(video_id, user_id, prompt)

        # Create initial status update
        await update_video_status(
            video_id=video_id,
            status="pending",
            step=0,
            step_message=initial_message
        )

    async def update(
        self,
        video_id: str,
        status: Optional[str] = None,
        step: Optional[int] = None,
        step_message: Optional[str] = None,
        error: Optional[str] = None,
        file_path: Optional[str] = None,
        duration: Optional[float] = None,
        subtitle_path: Optional[str] = None
    ) -> None:
        """
        Update video status in the database.

        Args:
            video_id: The video ID to update
            status: Current status (pending, processing, completed, failed)
            step: Current step number
            step_message: Description of current step
            error: Error message if status is failed
            file_path: Path to the generated video file
            duration: Video duration in seconds
            subtitle_path: Path to subtitle file if generated
        """
        # Get current status from database if we need to preserve values
        # For now, we'll use the provided values or None
        await update_video_status(
            video_id=video_id,
            status=status or "processing",
            step=step or 0,
            step_message=step_message or "",
            error=error,
            video_url=file_path,
            subtitle_path=subtitle_path,
            duration=duration
        )


# Global status tracker instance
status_tracker = StatusTracker()
