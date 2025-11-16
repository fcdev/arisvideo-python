"""
Video processing service for Manim execution and video operations.
"""

import os
import re
import asyncio
import shutil
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


async def execute_manim_script(script_path: str, animation_id: str, resolution: str) -> str:
    """
    Execute the generated Manim script and return the path to the generated video.
    """
    try:
        # Create output directory for this animation
        output_dir = f"temp_output/{animation_id}"
        os.makedirs(output_dir, exist_ok=True)
        
        # Run manim command
        cmd = [
            "manim",
            "render",
            "-q", resolution,
            "--output_file", f"{animation_id}",
            "--media_dir", output_dir,
            script_path
        ]
        
        # Execute manim
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"Manim execution failed: {stderr.decode()}")
        
        # Find the generated video file
        video_files = list(Path(output_dir).rglob("*.mp4"))
        if not video_files:
            raise Exception("No video file generated")
        
        return str(video_files[0])
        
    except Exception as e:
        raise Exception(f"Failed to execute Manim script: {str(e)}")


async def get_video_duration(video_path: str) -> float:
    """
    Get the duration of a video file using FFmpeg.
    """
    try:
        ffmpeg_path = shutil.which("ffmpeg") or os.path.expanduser("~/bin/ffmpeg")
        
        # Use ffmpeg with -i to get duration from stderr
        cmd = [
            ffmpeg_path,
            "-i", video_path,
            "-f", "null", "-",
            "-hide_banner"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        # Parse duration from stderr output
        stderr_text = stderr.decode()
        logger.debug(f"FFmpeg stderr output: {stderr_text[:200]}...")
        
        # Look for "Duration: HH:MM:SS.ms" pattern
        import re
        duration_match = re.search(r'Duration: (\d{2}):(\d{2}):(\d{2})\.(\d{2})', stderr_text)
        
        if duration_match:
            hours = int(duration_match.group(1))
            minutes = int(duration_match.group(2))
            seconds = int(duration_match.group(3))
            centiseconds = int(duration_match.group(4))
            
            total_seconds = hours * 3600 + minutes * 60 + seconds + centiseconds / 100
            logger.info(f"Detected video duration: {total_seconds:.2f}s")
            return total_seconds
        else:
            # Try alternative pattern with milliseconds
            duration_match = re.search(r'Duration: (\d{2}):(\d{2}):(\d{2})\.(\d{3})', stderr_text)
            if duration_match:
                hours = int(duration_match.group(1))
                minutes = int(duration_match.group(2))
                seconds = int(duration_match.group(3))
                milliseconds = int(duration_match.group(4))
                
                total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
                logger.info(f"Detected video duration: {total_seconds:.2f}s")
                return total_seconds
            else:
                logger.warning("Could not parse duration from ffmpeg output, using default estimate")
                return 50.0  # Default to 50 seconds for educational content with proper pacing
            
    except Exception as e:
        logger.warning(f"Failed to get video duration: {str(e)}, using default")
        return 50.0


async def check_ffmpeg_available() -> bool:
    """Check if FFmpeg is available on the system."""
    try:
        ffmpeg_path = shutil.which("ffmpeg") or os.path.expanduser("~/bin/ffmpeg")
        process = await asyncio.create_subprocess_exec(
            ffmpeg_path, "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        return process.returncode == 0
    except FileNotFoundError:
        return False


async def combine_audio_video(video_path: str, audio_path: str, output_path: str, video_duration: Optional[float] = None) -> None:
    """
    Combine audio and video using FFmpeg.
    Ensures full audio plays by extending video if necessary.
    """
    from .audio_processor import get_audio_duration

    try:
        # Check if FFmpeg is available
        if not await check_ffmpeg_available():
            raise Exception(
                "FFmpeg is not installed. Please install it using:\n"
                "macOS: brew install ffmpeg\n"
                "Ubuntu: sudo apt install ffmpeg\n"
                "Windows: Download from https://ffmpeg.org/download.html"
            )

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Use FFmpeg to combine audio and video with better synchronization
        ffmpeg_path = shutil.which("ffmpeg") or os.path.expanduser("~/bin/ffmpeg")

        # ALWAYS get both durations to prevent audio truncation
        audio_duration = await get_audio_duration(audio_path)
        if not video_duration:
            video_duration = await get_video_duration(video_path)

        logger.info(f"Video duration: {video_duration:.2f}s, Audio duration: {audio_duration:.2f}s")

        # Handle different audio/video duration scenarios for better educational pacing
        if video_duration and audio_duration:
            duration_ratio = audio_duration / video_duration
            logger.info(f"Duration ratio (audio/video): {duration_ratio:.2f}")
            
            if duration_ratio < 0.7:
                # Audio much shorter - add silence at end
                logger.info(f"Audio ({audio_duration:.1f}s) shorter than video ({video_duration:.1f}s), padding audio...")
                cmd = [
                    ffmpeg_path,
                    "-i", video_path,
                    "-i", audio_path,
                    "-filter_complex", f"[1:a]apad=whole_dur={video_duration}[audio]",
                    "-map", "0:v", "-map", "[audio]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-t", str(video_duration),  # Use video duration instead of -shortest
                    "-avoid_negative_ts", "make_zero",
                    "-fflags", "+genpts",
                    "-y",
                    output_path
                ]
            elif duration_ratio > 1.05:  # Changed from 1.1 to 1.05 for better sync
                # Audio longer - extend video by freezing last frame instead of looping
                logger.info(f"Audio ({audio_duration:.1f}s) longer than video ({video_duration:.1f}s), extending video with freeze frame...")
                
                # First, extend the video by freezing the last frame
                extended_video_path = f"temp_output/{os.path.basename(video_path)}_extended.mp4"
                
                # Calculate how much to extend
                extension_duration = audio_duration - video_duration + 1  # Add 1 second buffer
                
                extend_cmd = [
                    ffmpeg_path,
                    "-i", video_path,
                    "-filter_complex", f"[0:v]tpad=stop_mode=clone:stop_duration={extension_duration}[extended_video]",
                    "-map", "[extended_video]",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-y",
                    extended_video_path
                ]
                
                logger.info("Extending video with freeze frame...")
                extend_process = await asyncio.create_subprocess_exec(
                    *extend_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await extend_process.communicate()
                
                if extend_process.returncode != 0:
                    logger.warning(f"Video extension failed: {stderr.decode()}")
                    logger.info("Falling back to video looping...")
                    cmd = [
                        ffmpeg_path,
                        "-stream_loop", "-1", "-i", video_path,
                        "-i", audio_path,
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-t", str(audio_duration),  # Use audio duration instead of -shortest
                        "-avoid_negative_ts", "make_zero",
                        "-fflags", "+genpts",
                        "-y",
                        output_path
                    ]
                else:
                    # Now combine extended video with audio
                    logger.info("Combining extended video with audio...")
                    cmd = [
                        ffmpeg_path,
                        "-i", extended_video_path,
                        "-i", audio_path,
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-t", str(audio_duration),  # Use audio duration to preserve full audio
                        "-avoid_negative_ts", "make_zero",
                        "-fflags", "+genpts",
                        "-y",
                        output_path
                    ]
                    
                    # Clean up extended video after combining
                    def cleanup_extended():
                        try:
                            os.remove(extended_video_path)
                        except:
                            pass
                    
                    import atexit
                    atexit.register(cleanup_extended)
            else:
                # Durations are close enough - combine normally but use audio duration
                logger.info(f"Durations are well-matched, combining normally...")
                cmd = [
                    ffmpeg_path,
                    "-i", video_path,
                    "-i", audio_path,
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-t", str(audio_duration),  # Use audio duration to preserve full audio
                    "-avoid_negative_ts", "make_zero",
                    "-fflags", "+genpts",
                    "-y",
                    output_path
                ]
        else:
            # Fallback: if we couldn't get durations, combine with audio duration preference
            logger.warning("Could not determine durations, using simple combination")
            cmd = [
                ffmpeg_path,
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-avoid_negative_ts", "make_zero",
                "-fflags", "+genpts",
                "-y",
                output_path
            ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"FFmpeg failed: {stderr.decode()}")
        
        logger.info(f"Audio-video combination completed: {output_path}")
        
    except Exception as e:
        raise Exception(f"Failed to combine audio and video: {str(e)}")