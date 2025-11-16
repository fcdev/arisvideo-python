"""
In-memory status tracking for video generation
"""
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from dataclasses import dataclass, field
import threading


@dataclass
class VideoStatus:
    """Status information for a video generation job"""
    video_id: str
    status: str  # pending, processing, completed, failed
    step: int
    step_message: str
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None
    file_path: Optional[str] = None
    duration: Optional[float] = None
    subtitle_path: Optional[str] = None


class StatusTracker:
    """Thread-safe in-memory status tracker"""

    def __init__(self, cleanup_after_hours: int = 1):
        self._statuses: Dict[str, VideoStatus] = {}
        self._lock = threading.Lock()
        self._cleanup_after = timedelta(hours=cleanup_after_hours)

    def create(self, video_id: str, initial_message: str = "Initializing") -> VideoStatus:
        """Create a new status entry"""
        with self._lock:
            status = VideoStatus(
                video_id=video_id,
                status="pending",
                step=0,
                step_message=initial_message
            )
            self._statuses[video_id] = status
            return status

    def update(self, video_id: str, status: Optional[str] = None,
               step: Optional[int] = None, step_message: Optional[str] = None,
               error: Optional[str] = None, file_path: Optional[str] = None,
               duration: Optional[float] = None, subtitle_path: Optional[str] = None) -> Optional[VideoStatus]:
        """Update an existing status entry"""
        with self._lock:
            if video_id not in self._statuses:
                return None

            entry = self._statuses[video_id]
            if status is not None:
                entry.status = status
            if step is not None:
                entry.step = step
            if step_message is not None:
                entry.step_message = step_message
            if error is not None:
                entry.error = error
            if file_path is not None:
                entry.file_path = file_path
            if duration is not None:
                entry.duration = duration
            if subtitle_path is not None:
                entry.subtitle_path = subtitle_path

            entry.updated_at = datetime.now()
            return entry

    def get(self, video_id: str) -> Optional[VideoStatus]:
        """Get status for a video ID"""
        with self._lock:
            return self._statuses.get(video_id)

    def cleanup_old(self) -> int:
        """Remove status entries older than cleanup threshold"""
        with self._lock:
            now = datetime.now()
            cutoff = now - self._cleanup_after

            old_ids = [
                vid for vid, status in self._statuses.items()
                if status.updated_at < cutoff
            ]

            for vid in old_ids:
                del self._statuses[vid]

            return len(old_ids)

    def get_all(self) -> List[VideoStatus]:
        """Get all status entries (for debugging)"""
        with self._lock:
            return list(self._statuses.values())


# Global status tracker instance
status_tracker = StatusTracker(cleanup_after_hours=1)
