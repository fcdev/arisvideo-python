"""
FastAPI application for Manim-based educational animation generation.
Simplified stateless video generation service - no auth, no database.
"""

import os
import asyncio
import shutil
import time
import logging
import mimetypes
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse

# Load environment variables from .env file
load_dotenv()

# Import our models
from models import AnimationRequest, AnimationResponse, FileUploadInfo

# Import API key auth middleware
from middleware.api_key_auth import verify_api_key

# Import our services
from services import (
    get_anthropic_client,
    generate_and_refine_manim_script,
    fix_manim_script_from_error,
    detect_language,
    estimate_narration_duration,
    execute_manim_script,
    get_video_duration,
    combine_audio_video,
    extract_animation_timing,
    generate_timed_narration,
    create_synchronized_audio,
    extract_narration_from_script,
    generate_tts_audio,
    add_subtitles_to_video,
    adjust_audio_duration
)
from services.audio_processor import get_audio_duration
from services.file_processor import get_file_processor, cleanup_file_processor
from services.status_tracker import status_tracker

# Import our utilities
from utils import (
    generate_animation_id,
    cleanup_temp_files,
    log_performance,
    validate_prompt
)

# Configure logging
import sys
from datetime import datetime

# Simplified color logging - just show steps and errors
class FilteredColorHandler(logging.StreamHandler):
    """Filtered color log handler - shows steps, errors, and warnings only"""

    COLORS = {
        'DEBUG': '\033[36m',
        'INFO': '\033[32m',
        'WARNING': '\033[33m',
        'ERROR': '\033[31m',
        'CRITICAL': '\033[35m',
        'RESET': '\033[0m'
    }

    def emit(self, record):
        try:
            message = record.getMessage()

            # Only show step, error, and warning messages
            is_step = any(keyword in message for keyword in ['Step', 'Starting', 'Completed', 'Service'])
            is_error = record.levelname in ['ERROR', 'CRITICAL']
            is_warning = record.levelname == 'WARNING'

            if not (is_step or is_error or is_warning):
                return  # Skip other logs

            # Add timestamp
            timestamp = datetime.now().strftime('%H:%M:%S')

            # Get color
            color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            reset = self.COLORS['RESET']

            # Format message
            if record.levelname == 'INFO' and is_step:
                if 'Starting' in message:
                    emoji = '🚀'
                elif 'Step' in message:
                    emoji = '📝'
                elif 'Completed' in message:
                    emoji = '✅'
                else:
                    emoji = 'ℹ️'
                formatted = f"{color}[{timestamp}] {emoji} {message}{reset}"
            else:
                level_emoji = {'WARNING': '⚠️', 'ERROR': '❌', 'CRITICAL': '🔥'}.get(record.levelname, 'ℹ️')
                formatted = f"{color}[{timestamp}] {level_emoji} [{record.levelname}] {message}{reset}"

            self.stream.write(formatted + '\n')
            self.flush()
        except Exception:
            self.handleError(record)

# Configure root logger
logging.basicConfig(level=logging.INFO, handlers=[FilteredColorHandler(sys.stdout)])
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="ArisVideo Generation Service",
    description="Stateless video generation microservice using Manim and AI",
    version="2.0.0"
)

# Configure CORS - restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create necessary directories
os.makedirs("media/videos", exist_ok=True)
os.makedirs("temp_scripts", exist_ok=True)
os.makedirs("temp_output", exist_ok=True)

# Mount static files for video serving
app.mount("/media", StaticFiles(directory="media"), name="media")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "arisvideo-python",
        "version": "2.0.0"
    }


@app.post("/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    api_key: None = Depends(verify_api_key)
):
    """
    Upload files and extract text content (PDF, DOCX, images with OCR).
    Returns extracted text for context.
    """
    file_processor = get_file_processor()
    processed_files = []
    all_extracted_text = []

    try:
        for file in files:
            # Validate file size
            file_content = await file.read()
            file_size = len(file_content)

            if not file_processor.validate_file_size(file_size):
                raise HTTPException(
                    status_code=400,
                    detail=f"File {file.filename} is too large. Maximum size is 50MB."
                )

            # Check file type
            content_type = file.content_type or mimetypes.guess_type(file.filename)[0]
            if not file_processor.is_supported_file_type(content_type):
                raise HTTPException(
                    status_code=400,
                    detail=f"File type {content_type} is not supported. Supported types: PDF, Word, Images, Text."
                )

            # Extract text content
            logger.info(f"Processing file: {file.filename} ({content_type})")
            extracted_text = await file_processor.extract_text_from_file(
                file_content, file.filename, content_type
            )

            file_info = {
                "filename": file.filename,
                "content_type": content_type,
                "size": file_size,
                "extracted_text": extracted_text
            }
            processed_files.append(file_info)

            if extracted_text:
                all_extracted_text.append(f"=== Content from {file.filename} ===\n{extracted_text}")

        # Combine all extracted text
        combined_text = "\n\n".join(all_extracted_text) if all_extracted_text else None

        return {
            "files": processed_files,
            "combined_text": combined_text,
            "total_files": len(files),
            "files_with_text": len([f for f in processed_files if f["extracted_text"]])
        }

    except Exception as e:
        logger.error(f"Error processing files: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing files: {str(e)}")
    finally:
        cleanup_file_processor()


@app.post("/generate", response_model=AnimationResponse)
async def generate_animation(
    request: AnimationRequest,
    api_key: None = Depends(verify_api_key)
):
    """
    Generate an educational animation based on the provided prompt.
    Returns immediately with video_id and processes generation in background.
    """
    animation_id = generate_animation_id()
    logger.info(f"🎬 Starting video generation: {animation_id}")

    # Validate prompt
    if not validate_prompt(request.prompt):
        raise HTTPException(status_code=400, detail="Invalid or unsafe prompt provided")

    # Create status tracking
    status_tracker.create(animation_id, "Initializing video generation")

    # Start background video generation task
    asyncio.create_task(generate_video_background(request, animation_id))

    # Return immediately with video_id
    return AnimationResponse(
        video_id=animation_id,
        video_url="",  # Will be set when generation completes
        status="processing",
        message="Video generation started successfully"
    )


async def generate_video_background(request: AnimationRequest, animation_id: str):
    """
    Background task to generate the video.
    """
    start_time = time.time()

    try:
        logger.info("=" * 120)
        logger.info(f"🎬 Starting Video Generation")
        logger.info(f"📹 Video ID: {animation_id}")
        logger.info(f"👤 Prompt: {request.prompt}")
        logger.info(f"🌐 Language: {request.language or 'auto-detect'}")
        logger.info(f"🎵 Audio: {'Yes' if request.include_audio else 'No'}")
        logger.info(f"📐 Resolution: {request.resolution}")
        logger.info("=" * 120)

        # Update status
        status_tracker.update(animation_id, status="processing", step=1, step_message="Generating Manim script")

        # Step 1: Generate and refine Manim script using Claude
        logger.info("📝 Step 1: Generating Manim script")

        client = get_anthropic_client()

        # Detect language from prompt first
        detected_language = request.language or await detect_language(client, request.prompt)

        # Estimate target duration for better sync
        if request.include_audio:
            target_duration = await estimate_narration_duration(client, request.prompt)
        else:
            target_duration = 45.0  # Default for videos without audio

        manim_script = await generate_and_refine_manim_script(
            client, request.prompt, max_attempts=3, target_duration=target_duration,
            language=detected_language, file_context=request.uploaded_files_context
        )
        logger.info("✅ Script generation completed")

        # Step 2: Save the generated script
        script_path = f"temp_scripts/{animation_id}.py"
        os.makedirs("temp_scripts", exist_ok=True)
        with open(script_path, "w", encoding='utf-8') as f:
            f.write(manim_script)

        # Step 3: Execute the Manim script
        logger.info("🎬 Step 2: Rendering animation")
        status_tracker.update(animation_id, step=2, step_message="Rendering animation")

        try:
            video_path = await execute_manim_script(script_path, animation_id, request.resolution)
            logger.info("✅ Animation rendering completed")

        except Exception as manim_error:
            logger.error(f"❌ Manim execution failed: {str(manim_error)}")
            # Try to regenerate script with error feedback
            logger.info("🔧 Attempting to fix script errors...")

            fixed_script = await fix_manim_script_from_error(client, manim_script, str(manim_error), detected_language)

            # Save fixed script
            with open(script_path, "w", encoding='utf-8') as f:
                f.write(fixed_script)

            # Retry execution
            video_path = await execute_manim_script(script_path, animation_id, request.resolution)
            logger.info("✅ Fixed script executed successfully")

        # Step 4: Generate audio if requested
        storage_path = os.getenv("VIDEO_STORAGE_PATH", "./media/videos")
        os.makedirs(storage_path, exist_ok=True)
        final_video_path = f"{storage_path}/{animation_id}.mp4"

        if request.include_audio:
            logger.info("🎵 Step 3: Generating audio")
            status_tracker.update(animation_id, step=3, step_message="Generating audio")

            # Get video duration for timing
            video_duration = await get_video_duration(video_path)

            # Handle different sync methods
            subtitle_path = None  # Track subtitle file path

            if request.sync_method == "timing_analysis":
                # Extract timing information from Manim script
                timing_segments = await extract_animation_timing(client, manim_script)

                # Generate synchronized narration
                narration_segments = await generate_timed_narration(
                    client, manim_script, request.prompt, detected_language, timing_segments
                )

                # Generate subtitle file from narration segments
                from services.audio_processor import generate_subtitle_file_from_segments
                temp_subtitle_path = await generate_subtitle_file_from_segments(
                    narration_segments, animation_id, format="srt"
                )
                # Save subtitle file to storage
                final_subtitle_path = f"{storage_path}/{animation_id}.srt"
                shutil.copy(temp_subtitle_path, final_subtitle_path)
                subtitle_path = final_subtitle_path
                logger.info(f"✅ Subtitle file saved: {final_subtitle_path}")

                # Create synchronized audio
                audio_path = await create_synchronized_audio(
                    narration_segments, animation_id, request.voice, detected_language
                )

            elif request.sync_method == "subtitle_overlay":
                narration_text = await extract_narration_from_script(
                    client, manim_script, request.prompt, detected_language, video_duration
                )
                audio_path = await generate_tts_audio(
                    narration_text, animation_id, request.voice, detected_language
                )
                # Add subtitles to video
                final_video_path = await add_subtitles_to_video(
                    video_path, narration_text, final_video_path, detected_language
                )
            else:  # Default fallback - improved simple method
                narration_text = await extract_narration_from_script(
                    client, manim_script, request.prompt, detected_language, video_duration
                )
                audio_path = await generate_tts_audio(
                    narration_text, animation_id, request.voice, detected_language
                )
                # Ensure audio duration matches video by padding or trimming
                audio_duration = await get_audio_duration(audio_path)

                if abs(audio_duration - video_duration) > 2.0:  # Significant difference
                    adjusted_audio_path = f"temp_output/{animation_id}_adjusted_audio.mp3"
                    os.makedirs("temp_output", exist_ok=True)
                    await adjust_audio_duration(audio_path, adjusted_audio_path, video_duration)
                    os.remove(audio_path)
                    audio_path = adjusted_audio_path

            if request.sync_method != "subtitle_overlay":
                logger.info("🎬 Step 4: Combining audio and video")
                status_tracker.update(animation_id, step=4, step_message="Combining audio and video")

                await combine_audio_video(video_path, audio_path, final_video_path, video_duration)
                logger.info("✅ Audio-video combination completed")

                # Clean up temporary audio
                os.remove(audio_path)
            else:
                # Add subtitles to video if using subtitle overlay
                await add_subtitles_to_video(video_path, narration_text, final_video_path, detected_language)
        else:
            # Move video to storage directory (no audio)
            shutil.move(video_path, final_video_path)

        # Get video duration for response
        video_duration = await get_video_duration(final_video_path)

        # Clean up temp script
        os.remove(script_path)

        # Log performance
        end_time = time.time()
        total_time = end_time - start_time
        log_performance("generate_animation", start_time, end_time)

        logger.info(f"🎉 Video generation completed! Time: {total_time:.1f}s")

        # Update final status
        status_tracker.update(
            animation_id,
            status="completed",
            step_message="Generation completed",
            file_path=final_video_path,
            duration=video_duration,
            subtitle_path=subtitle_path
        )

        # Clean up file processor
        cleanup_file_processor()

    except Exception as e:
        # Update error status
        logger.error(f"❌ Video generation failed: {str(e)}")
        status_tracker.update(
            animation_id,
            status="failed",
            step_message=f"Generation failed: {str(e)}",
            error=str(e)
        )

        # Clean up any partial files
        cleanup_temp_files(animation_id)

        # Clean up file processor
        cleanup_file_processor()


@app.get("/status/{video_id}")
async def get_video_status(
    video_id: str,
    api_key: None = Depends(verify_api_key)
):
    """
    Get the generation status for a video.
    Fallback to checking disk if in-memory status is missing (handles restarts).
    """
    status = status_tracker.get(video_id)

    if not status:
        # Fallback: check if video file exists on disk
        # This handles cases where backend restarted and lost in-memory status
        storage_path = os.getenv("VIDEO_STORAGE_PATH", "./media/videos")
        video_path = f"{storage_path}/{video_id}.mp4"

        if os.path.exists(video_path):
            # Video exists on disk, return completed status
            try:
                duration = await get_video_duration(video_path)
            except:
                duration = None

            file_stat = os.stat(video_path)
            created_time = datetime.fromtimestamp(file_stat.st_ctime)
            modified_time = datetime.fromtimestamp(file_stat.st_mtime)

            return {
                "video_id": video_id,
                "status": "completed",
                "step": 4,
                "message": "Video generation completed (recovered from disk)",
                "file_path": video_path,
                "duration": duration,
                "error": None,
                "created_at": created_time.isoformat(),
                "updated_at": modified_time.isoformat()
            }
        else:
            raise HTTPException(status_code=404, detail="Video not found")

    return {
        "video_id": status.video_id,
        "status": status.status,
        "step": status.step,
        "message": status.step_message,
        "file_path": status.file_path,
        "duration": status.duration,
        "error": status.error,
        "created_at": status.created_at.isoformat(),
        "updated_at": status.updated_at.isoformat()
    }


@app.get("/video/{video_id}")
async def stream_video(
    video_id: str,
    request: Request,
    api_key: None = Depends(verify_api_key)
):
    """
    Stream video file with range request support for proper playback and seeking.
    Supports HTTP range requests (HTTP 206 Partial Content) for efficient streaming.
    """
    storage_path = os.getenv("VIDEO_STORAGE_PATH", "./media/videos")
    video_path = f"{storage_path}/{video_id}.mp4"

    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video file not found")

    # Get file size
    file_size = os.stat(video_path).st_size

    # Parse Range header
    range_header = request.headers.get("range")

    if range_header:
        # Parse range header (format: "bytes=start-end")
        range_match = range_header.replace("bytes=", "").split("-")
        start = int(range_match[0]) if range_match[0] else 0
        end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else file_size - 1

        # Ensure valid range
        start = max(0, min(start, file_size - 1))
        end = max(start, min(end, file_size - 1))
        content_length = end - start + 1

        # Stream partial content
        def iterfile():
            with open(video_path, "rb") as f:
                f.seek(start)
                remaining = content_length
                chunk_size = 8192
                while remaining > 0:
                    chunk = f.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
            "Content-Type": "video/mp4",
        }

        return StreamingResponse(
            iterfile(),
            status_code=206,
            headers=headers,
            media_type="video/mp4"
        )

    else:
        # Stream full file
        def iterfile():
            with open(video_path, "rb") as f:
                chunk_size = 8192
                while chunk := f.read(chunk_size):
                    yield chunk

        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": "video/mp4",
        }

        return StreamingResponse(
            iterfile(),
            headers=headers,
            media_type="video/mp4"
        )


@app.get("/subtitle/{video_id}")
async def get_subtitle_file(
    video_id: str,
    api_key: None = Depends(verify_api_key)
):
    """
    Download subtitle file for a video (SRT format).
    Returns 404 if subtitle file doesn't exist.
    """
    storage_path = os.getenv("VIDEO_STORAGE_PATH", "./media/videos")
    subtitle_path = f"{storage_path}/{video_id}.srt"

    if not os.path.exists(subtitle_path):
        raise HTTPException(status_code=404, detail="Subtitle file not found")

    return FileResponse(
        subtitle_path,
        media_type="application/x-subrip",
        filename=f"{video_id}.srt"
    )


@app.get("/cleanup")
async def cleanup_old_status(
    api_key: None = Depends(verify_api_key)
):
    """
    Cleanup old status entries (admin endpoint).
    """
    cleaned = status_tracker.cleanup_old()
    return {
        "message": f"Cleaned up {cleaned} old status entries"
    }


if __name__ == "__main__":
    import uvicorn

    # Print startup info
    print("🚀 ArisVideo Generation Service Starting...")
    print("🌐 Service address: http://0.0.0.0:8000")
    print("🔧 HTTP version: 1.1")
    print("=" * 40)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        http="h11",  # Force HTTP/1.1
        proxy_headers=True,
        forwarded_allow_ips="*"
    )
