"""
Pydantic models for the Manimations API.
"""

from pydantic import BaseModel
from typing import Optional, List
from fastapi import UploadFile


class FileUploadInfo(BaseModel):
    """Information about an uploaded file."""
    filename: str
    content_type: str
    size: int
    extracted_text: Optional[str] = None


class AnimationRequest(BaseModel):
    """Request model for animation generation."""
    prompt: str
    resolution: str = "m"  # Default resolution: l=low, m=medium, h=high, p=production, k=4k
    include_audio: bool = True  # Whether to generate audio narration
    voice: str = "alloy"  # OpenAI voice: alloy, echo, fable, onyx, nova, shimmer
    language: Optional[str] = None  # Language code (auto-detected if None)
    sync_method: str = "timing_analysis"  # "timing_analysis", "narration_first", "subtitle_overlay"
    uploaded_files_context: Optional[str] = None  # Extracted text content from uploaded files
    timing_adjustment_threshold: float = 0.1  # Minimum duration mismatch (seconds) to trigger script adjustment


class AnimationResponse(BaseModel):
    """Response model for animation generation."""
    video_id: str
    video_url: str
    status: str
    message: str = ""


class AnimationStatus(BaseModel):
    """Model for animation generation status tracking."""
    animation_id: str
    status: str  # "generating", "refining", "rendering", "completed", "failed"
    progress: int = 0  # 0-100
    current_step: str = ""
    error_message: str = ""