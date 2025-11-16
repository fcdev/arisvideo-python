"""
Audio processing service for TTS generation and audio synchronization.
"""

import os
import re
import asyncio
import shutil
from typing import List, Dict, Any, Optional
import anthropic
from anthropic.types import TextBlock
import openai
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)


def get_openai_client():
    """Initialize OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")
    return openai.OpenAI(api_key=api_key)


def extract_text_from_content(content) -> str:
    """
    Safely extract text from Anthropic content blocks.
    """
    if isinstance(content, TextBlock):
        return content.text
    else:
        return str(content)


async def get_audio_duration(audio_path: str) -> float:
    """
    Get the duration of an audio file using FFmpeg.
    """
    try:
        ffmpeg_path = shutil.which("ffmpeg") or os.path.expanduser("~/bin/ffmpeg")
        
        # Use ffmpeg with -i to get duration from stderr
        cmd = [
            ffmpeg_path,
            "-i", audio_path,
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
                return total_seconds
            else:
                logger.warning("Could not parse audio duration from ffmpeg output")
                return 10.0  # Default estimate
            
    except Exception as e:
        logger.warning(f"Failed to get audio duration: {str(e)}")
        return 10.0


async def adjust_audio_duration(input_path: str, output_path: str, target_duration: float) -> None:
    """
    Adjust audio duration to match video by padding with silence or looping.
    """
    try:
        ffmpeg_path = shutil.which("ffmpeg") or os.path.expanduser("~/bin/ffmpeg")
        
        # Get current audio duration
        current_duration = await get_audio_duration(input_path)
        
        if current_duration < target_duration:
            # Audio is shorter - pad with silence at the end
            silence_duration = target_duration - current_duration
            logger.info(f"Padding audio with {silence_duration:.2f}s of silence")
            
            cmd = [
                ffmpeg_path,
                "-i", input_path,
                "-filter_complex", f"[0:a]apad=whole_dur={target_duration}[out]",
                "-map", "[out]",
                "-c:a", "mp3",
                "-y",
                output_path
            ]
        else:
            # Audio is longer - trim to target duration
            logger.info(f"Trimming audio from {current_duration:.2f}s to {target_duration:.2f}s")
            
            cmd = [
                ffmpeg_path,
                "-i", input_path,
                "-t", str(target_duration),
                "-c:a", "mp3",
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
            raise Exception(f"FFmpeg audio adjustment failed: {stderr.decode()}")
        
        logger.info(f"Audio duration adjusted to {target_duration:.2f}s")
        
    except Exception as e:
        raise Exception(f"Failed to adjust audio duration: {str(e)}")


async def extract_animation_timing(client: anthropic.Anthropic, manim_script: str) -> List[Dict[str, Any]]:
    """
    Extract timing segments from Manim script by analyzing animations and waits.
    """
    system_prompt = """Analyze the Manim script and extract timing information for each animation segment.

    Look for:
    - self.play() calls with run_time parameters
    - self.wait() calls 
    - Animation sequences and their durations
    - Visual elements being introduced

    Return a JSON list of timing segments like:
    [
        {"start_time": 0, "end_time": 3, "description": "Title and theorem introduction", "content": "Pythagorean theorem"},
        {"start_time": 3, "end_time": 8, "description": "Triangle creation", "content": "Creating right triangle"},
        {"start_time": 8, "end_time": 15, "description": "Squares visualization", "content": "Drawing squares on each side"}
    ]

    Estimate timing based on:
    - Default play() duration: 1 second
    - run_time=X: X seconds  
    - self.wait(X): X seconds
    - Complex animations: add 1-2 seconds

    Return ONLY the JSON array, no explanations."""
    
    try:
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"Analyze timing for this Manim script:\n\n{manim_script}"
                }
            ]
        )
        
        content = message.content[0]
        timing_text = extract_text_from_content(content)
        
        # Parse JSON response
        import json
        try:
            timing_segments = json.loads(timing_text)
            return timing_segments
        except json.JSONDecodeError:
            # Fallback to basic timing
            logger.warning("Could not parse timing JSON, using fallback")
            return [
                {"start_time": 0, "end_time": 10, "description": "Introduction", "content": "Animation introduction"},
                {"start_time": 10, "end_time": 20, "description": "Main content", "content": "Main educational content"},
                {"start_time": 20, "end_time": 30, "description": "Conclusion", "content": "Summary and conclusion"}
            ]
        
    except Exception as e:
        logger.warning(f"Failed to extract timing: {str(e)}, using fallback")
        return [
            {"start_time": 0, "end_time": 10, "description": "Introduction", "content": "Animation introduction"},
            {"start_time": 10, "end_time": 20, "description": "Main content", "content": "Main educational content"},
            {"start_time": 20, "end_time": 30, "description": "Conclusion", "content": "Summary and conclusion"}
        ]


async def generate_timed_narration(
    client: anthropic.Anthropic,
    manim_script: str,
    original_prompt: str,
    language: str,
    timing_segments: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Generate narration segments that match the timing of the animation.
    """
    language_names = {
        'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German',
        'it': 'Italian', 'pt': 'Portuguese', 'ru': 'Russian', 'ja': 'Japanese',
        'ko': 'Korean', 'zh': 'Chinese', 'ar': 'Arabic', 'hi': 'Hindi'
    }
    
    system_prompt = f"""Create timed narration segments that match the animation timing exactly.

    For each timing segment, create narration that:
    1. Fits within the specified time duration
    2. Explains what's happening visually during that time
    3. Uses clear, educational language in {language_names.get(language, 'English')}
    4. Matches the pacing (words per minute should fit the duration)

    Return JSON format:
    [
        {{
            "start_time": 0,
            "end_time": 3,
            "text": "Welcome! Today we'll explore the famous Pythagorean theorem.",
            "words": 9
        }},
        {{
            "start_time": 3,
            "end_time": 8, 
            "text": "Let's start by creating a right triangle to see how this works.",
            "words": 12
        }}
    ]

    Pacing guide: ~2-3 words per second for comfortable listening.
    Return ONLY the JSON array."""
    
    timing_info = "\n".join([f"Segment {i+1}: {seg['start_time']}-{seg['end_time']}s - {seg['description']}" 
                           for i, seg in enumerate(timing_segments)])
    
    try:
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=3000,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"Original prompt: {original_prompt}\n\nTiming segments:\n{timing_info}\n\nManim script:\n{manim_script}\n\nCreate timed narration:"
                }
            ]
        )
        
        content = message.content[0]
        narration_text = extract_text_from_content(content)
        
        import json
        try:
            narration_segments = json.loads(narration_text)
            
            # Validate and clean segments
            cleaned_segments = []
            for i, segment in enumerate(narration_segments):
                text = segment.get("text", "").strip()
                start_time = segment.get("start_time", 0)
                end_time = segment.get("end_time", 10)
                
                # Skip empty segments or fix them
                if not text or len(text) < 3:
                    logger.warning(f"Segment {i} has empty or very short text: '{text}', using fallback")
                    text = f"Animation segment {i+1}."
                
                # Ensure timing makes sense
                if end_time <= start_time:
                    end_time = start_time + 3  # Default 3 second duration
                
                cleaned_segments.append({
                    "start_time": start_time,
                    "end_time": end_time,
                    "text": text,
                    "words": len(text.split())
                })
            
            return cleaned_segments
            
        except json.JSONDecodeError:
            # Fallback
            logger.warning("Could not parse narration JSON, using fallback")
            return [
                {"start_time": 0, "end_time": len(timing_segments) * 10, 
                 "text": "Educational animation explaining the concept step by step.", "words": 8}
            ]
        
    except Exception as e:
        logger.warning(f"Failed to generate timed narration: {str(e)}")
        return [
            {"start_time": 0, "end_time": 30, 
             "text": "Educational animation explaining the concept step by step.", "words": 8}
        ]


async def create_synchronized_audio(
    narration_segments: List[Dict[str, Any]],
    animation_id: str,
    voice: str,
    language: str
) -> str:
    """
    Create audio with precise timing using silence padding.
    """
    try:
        client = get_openai_client()
        audio_segments = []
        
        # Filter out empty or invalid segments
        valid_segments = []
        for segment in narration_segments:
            text = segment.get("text", "").strip()
            if text and len(text) > 0:
                valid_segments.append(segment)
            else:
                logger.warning(f"Skipping empty segment: {segment}")
        
        if not valid_segments:
            raise Exception("No valid narration segments found - all segments are empty")
        
        logger.info(f"Processing {len(valid_segments)} valid segments out of {len(narration_segments)} total")
        
        # Pick the most natural-sounding voice for the requested language
        selected_voice = get_voice_for_language(language, voice)
        logger.info(f"Syncing narration: language={language}, voice={selected_voice}")
        
        for i, segment in enumerate(valid_segments):
            text = segment["text"].strip()
            
            # Ensure text is not empty and has minimum length
            if len(text) < 3:
                text = "Pause."  # Fallback for very short segments
            
            logger.info(f"Generating TTS segment {i}: '{text[:50]}...'")
            
            # Generate TTS for this segment
            response = client.audio.speech.create(
                model="tts-1",
                voice=selected_voice,
                input=text,
                response_format="mp3",
                speed=0.85
            )
            
            # Save segment audio
            segment_path = f"temp_output/{animation_id}_segment_{i}.mp3"
            os.makedirs(os.path.dirname(segment_path), exist_ok=True)
            
            with open(segment_path, "wb") as f:
                f.write(response.content)
            
            audio_segments.append({
                "path": segment_path,
                "start_time": segment["start_time"],
                "end_time": segment["end_time"],
                "text": text
            })
        
        # Combine segments with precise timing using FFmpeg
        final_audio_path = f"temp_output/{animation_id}_synced_audio.mp3"
        await combine_audio_segments(audio_segments, final_audio_path)
        
        # Clean up segment files
        for segment in audio_segments:
            try:
                os.remove(segment["path"])
            except:
                pass
        
        return final_audio_path
        
    except Exception as e:
        raise Exception(f"Failed to create synchronized audio: {str(e)}")


async def combine_audio_segments(segments: List[Dict[str, Any]], output_path: str) -> None:
    """
    Combine audio segments with precise timing using FFmpeg.
    """
    try:
        ffmpeg_path = shutil.which("ffmpeg") or os.path.expanduser("~/bin/ffmpeg")
        
        # Use a simpler approach: create silent base track and overlay segments
        if len(segments) == 0:
            raise Exception("No audio segments to combine")
        
        # Calculate total duration needed (ensure it covers full video)
        max_end_time = max(seg["end_time"] for seg in segments)
        # Add buffer to ensure we don't cut off audio
        total_duration = max_end_time + 2.0
        
        logger.info(f"Creating base track with duration: {total_duration}s (max segment end: {max_end_time}s)")
        
        # Create silent base track
        base_cmd = [
            ffmpeg_path,
            "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={total_duration}",
            "-c:a", "mp3",
            "-y",
            f"temp_output/base_{os.path.basename(output_path)}"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *base_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        if process.returncode != 0:
            # Fallback: just concatenate all segments sequentially
            logger.warning("Complex timing failed, using sequential concatenation")
            await concatenate_audio_segments_simple(segments, output_path)
            return
        
        # Use a different approach: overlay all segments at once instead of iterative overlay
        # This prevents losing early segments
        
        logger.info("Overlaying all segments simultaneously...")
        
        # Build filter complex for all segments at once
        current_file = f"temp_output/base_{os.path.basename(output_path)}"
        input_files = ["-i", current_file]  # Base silent track
        filter_parts = []
        
        # Add all segment files as inputs
        for i, segment in enumerate(segments):
            input_files.extend(["-i", segment["path"]])
            start_time_ms = int(segment["start_time"] * 1000)
            logger.info(f"Adding segment {i} at {segment['start_time']}s ({start_time_ms}ms)")
            
            # Delay each segment to its start time
            if start_time_ms > 0:
                filter_parts.append(f"[{i+1}:a]adelay={start_time_ms}|{start_time_ms}[delayed{i}]")
            else:
                filter_parts.append(f"[{i+1}:a]anull[delayed{i}]")
        
        # Mix all delayed segments with the base track
        if len(segments) == 1:
            # Special case for single segment
            filter_complex = f"{filter_parts[0]};[0:a][delayed0]amix=inputs=2:duration=first[out]"
        else:
            # Multiple segments
            delayed_inputs = "+".join([f"[delayed{i}]" for i in range(len(segments))])
            filter_complex = ";".join(filter_parts) + f";[0:a]{delayed_inputs}amix=inputs={len(segments)+1}:duration=first[out]"
        
        final_output_file = f"temp_output/final_{os.path.basename(output_path)}"
        
        cmd = [
            ffmpeg_path,
            *input_files,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:a", "mp3",
            "-y",
            final_output_file
        ]
        
        logger.info(f"FFmpeg command: {' '.join(cmd)}")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            logger.warning(f"Simultaneous overlay failed: {stderr.decode()}")
            logger.warning("Falling back to simple segment-by-segment approach")
            await create_simple_timed_audio(segments, output_path)
            return
        
        current_file = final_output_file
        
        # Move final result to output path
        shutil.move(current_file, output_path)
        
        # Clean up base file
        try:
            os.remove(f"temp_output/base_{os.path.basename(output_path)}")
        except:
            pass
        
        logger.info(f"Synchronized audio created: {output_path}")
        
    except Exception as e:
        logger.warning(f"Complex audio timing failed: {str(e)}, using simple concatenation")
        await create_simple_timed_audio(segments, output_path)


async def create_simple_timed_audio(segments: List[Dict[str, Any]], output_path: str) -> None:
    """
    Create timed audio by building a sequence with silence and audio segments.
    This method ensures all segments are included and properly timed.
    """
    try:
        ffmpeg_path = shutil.which("ffmpeg") or os.path.expanduser("~/bin/ffmpeg")
        
        if not segments:
            raise Exception("No segments to process")
        
        # Sort segments by start time to ensure correct order
        sorted_segments = sorted(segments, key=lambda x: x["start_time"])
        
        # Build a sequence of silence and audio parts
        sequence_parts = []
        current_time = 0.0
        
        for i, segment in enumerate(sorted_segments):
            start_time = segment["start_time"]
            
            # Add silence if there's a gap
            if start_time > current_time:
                silence_duration = start_time - current_time
                logger.info(f"Adding {silence_duration:.2f}s silence before segment {i}")
                sequence_parts.append({
                    "type": "silence",
                    "duration": silence_duration,
                    "start": current_time,
                    "end": start_time
                })
            
            # Add the audio segment
            logger.info(f"Adding segment {i} from {start_time:.2f}s")
            sequence_parts.append({
                "type": "audio",
                "path": segment["path"],
                "start": start_time,
                "end": segment["end_time"]
            })
            
            current_time = segment["end_time"]
        
        # Create the final sequence using concat demuxer
        concat_file = f"temp_output/sequence_{os.path.basename(output_path)}.txt"
        temp_files = []
        
        with open(concat_file, "w") as f:
            for i, part in enumerate(sequence_parts):
                if part["type"] == "silence":
                    # Create silence file
                    silence_file = f"temp_output/silence_{i}_{os.path.basename(output_path)}.mp3"
                    silence_cmd = [
                        ffmpeg_path,
                        "-f", "lavfi",
                        "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={part['duration']}",
                        "-c:a", "mp3",
                        "-y",
                        silence_file
                    ]
                    
                    process = await asyncio.create_subprocess_exec(
                        *silence_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await process.communicate()
                    
                    if process.returncode == 0:
                        f.write(f"file '{os.path.abspath(silence_file)}'\n")
                        temp_files.append(silence_file)
                    
                elif part["type"] == "audio":
                    f.write(f"file '{os.path.abspath(part['path'])}'\n")
        
        # Concatenate all parts
        cmd = [
            ffmpeg_path,
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c:a", "mp3",
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
            raise Exception(f"Simple timed audio failed: {stderr.decode()}")
        
        # Clean up temporary files
        try:
            os.remove(concat_file)
            for temp_file in temp_files:
                os.remove(temp_file)
        except:
            pass
        
        logger.info(f"Simple timed audio created successfully: {output_path}")
        
    except Exception as e:
        logger.warning(f"Simple timed audio failed: {str(e)}, using basic concatenation")
        await concatenate_audio_segments_simple(segments, output_path)


async def concatenate_audio_segments_simple(segments: List[Dict[str, Any]], output_path: str) -> None:
    """
    Simple fallback: concatenate audio segments sequentially with silence padding.
    """
    try:
        ffmpeg_path = shutil.which("ffmpeg") or os.path.expanduser("~/bin/ffmpeg")
        
        # Create list of inputs with silence padding
        input_files = []
        filter_parts = []
        
        for i, segment in enumerate(segments):
            input_files.extend(["-i", segment["path"]])
            
            # Calculate proper timing for each segment
            if i == 0:
                # First segment: add silence before if needed
                silence_before = segment["start_time"]
                if silence_before > 0:
                    filter_parts.append(f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={silence_before}[silence_before_{i}]")
                    filter_parts.append(f"[silence_before_{i}][{i}:a]concat=n=2:v=0:a=1[padded{i}]")
                else:
                    filter_parts.append(f"[{i}:a]anull[padded{i}]")
            else:
                # Subsequent segments: calculate gap from previous segment
                prev_segment = segments[i-1]
                gap_duration = segment["start_time"] - prev_segment["end_time"]
                
                if gap_duration > 0:
                    # Add silence gap between segments
                    filter_parts.append(f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={gap_duration}[gap_{i}]")
                    filter_parts.append(f"[gap_{i}][{i}:a]concat=n=2:v=0:a=1[padded{i}]")
                else:
                    filter_parts.append(f"[{i}:a]anull[padded{i}]")
        
        # Concatenate all padded segments
        concat_inputs = "".join([f"[padded{i}]" for i in range(len(segments))])
        filter_parts.append(f"{concat_inputs}concat=n={len(segments)}:v=0:a=1[out]")
        
        filter_complex = ";".join(filter_parts)
        
        cmd = [
            ffmpeg_path,
            *input_files,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:a", "mp3",
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
            # Last resort: just concatenate without timing
            logger.warning("All audio timing failed, using basic concatenation")
            
            # Create a simple concatenation list file
            concat_file = f"temp_output/concat_{os.path.basename(output_path)}.txt"
            with open(concat_file, "w") as f:
                for segment in segments:
                    f.write(f"file '{os.path.abspath(segment['path'])}'\n")
            
            cmd = [
                ffmpeg_path,
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c:a", "mp3",
                "-y",
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await process.communicate()
            
            # Clean up
            try:
                os.remove(concat_file)
            except:
                pass
        
        logger.info(f"Audio segments combined: {output_path}")
        
    except Exception as e:
        raise Exception(f"Failed to concatenate audio segments: {str(e)}")


async def add_subtitles_to_video(
    video_path: str,
    narration_text: str,
    output_path: str,
    language: str
) -> str:
    """
    Add subtitles to video as an alternative to audio sync.
    """
    from .video_processor import get_video_duration
    
    try:
        ffmpeg_path = shutil.which("ffmpeg") or os.path.expanduser("~/bin/ffmpeg")
        
        # Create simple SRT subtitle file
        subtitle_path = f"temp_output/{os.path.basename(video_path)}_subtitles.srt"
        os.makedirs(os.path.dirname(subtitle_path), exist_ok=True)
        
        # Simple subtitle timing (split narration into chunks)
        words = narration_text.split()
        chunk_size = 8  # words per subtitle
        chunks = [words[i:i+chunk_size] for i in range(0, len(words), chunk_size)]
        
        video_duration = await get_video_duration(video_path)
        time_per_chunk = video_duration / len(chunks)
        
        with open(subtitle_path, "w", encoding="utf-8") as f:
            for i, chunk in enumerate(chunks):
                start_time = i * time_per_chunk
                end_time = (i + 1) * time_per_chunk
                
                # SRT time format: HH:MM:SS,mmm
                start_srt = f"{int(start_time//3600):02d}:{int((start_time%3600)//60):02d}:{int(start_time%60):02d},{int((start_time%1)*1000):03d}"
                end_srt = f"{int(end_time//3600):02d}:{int((end_time%3600)//60):02d}:{int(end_time%60):02d},{int((end_time%1)*1000):03d}"
                
                f.write(f"{i+1}\n")
                f.write(f"{start_srt} --> {end_srt}\n")
                f.write(f"{' '.join(chunk)}\n\n")
        
        # Add subtitles to video
        cmd = [
            ffmpeg_path,
            "-i", video_path,
            "-vf", f"subtitles={subtitle_path}:force_style='FontSize=20,FontName=Arial,PrimaryColour=&Hffffff,OutlineColour=&H000000,Outline=2'",
            "-c:a", "copy",
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
            raise Exception(f"FFmpeg subtitle overlay failed: {stderr.decode()}")
        
        # Clean up subtitle file
        try:
            os.remove(subtitle_path)
        except:
            pass
        
        logger.info(f"Subtitles added to video: {output_path}")
        return output_path
        
    except Exception as e:
        raise Exception(f"Failed to add subtitles: {str(e)}")


async def extract_narration_from_script(
    client: anthropic.Anthropic, 
    manim_script: str, 
    original_prompt: str,
    language: str = 'en',
    video_duration: float = 15.0
) -> str:
    """
    Extract educational narration text from the Manim script using Claude.
    """
    language_names = {
        'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German',
        'it': 'Italian', 'pt': 'Portuguese', 'ru': 'Russian', 'ja': 'Japanese',
        'ko': 'Korean', 'zh': 'Chinese', 'ar': 'Arabic', 'hi': 'Hindi'
    }
    
    system_prompt = f"""You are an educational content expert. Analyze the provided Manim script and original prompt to create a clear, engaging narration for the educational animation.

    Requirements:
    1. Create a natural, conversational narration that explains the concepts
    2. Time the narration to match the video duration ({video_duration:.1f} seconds)
    3. Use educational language appropriate for the target audience
    4. Include explanations of what's happening visually
    5. Make it engaging and easy to follow
    6. Keep sentences clear and not too long for good TTS delivery
    7. Write the narration in {language_names.get(language, 'English')}
    8. Pace the narration to be spoken naturally within {video_duration:.1f} seconds
    9. Return ONLY the narration text, no additional formatting or explanations

    PACING Guidelines for Narration:
    - Speak at a moderate, educational pace (about 150-180 words per minute)
    - Use short, clear sentences that are easy to follow
    - Add natural pauses between concepts (use periods and commas)
    - Include phrases like "Let's see...", "Now observe...", "Notice that..." for pacing
    - Leave time for viewers to absorb visual information
    - Don't rush through explanations - clarity over speed
    - Structure: Introduction → Step-by-step explanation → Conclusion

    The narration should guide viewers through the animation at a comfortable learning pace, explaining concepts as they appear on screen. Make sure the narration timing matches the visual flow of the animation."""
    
    try:
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            system=system_prompt,
            messages=[
                {
                    "role": "user", 
                    "content": f"Original prompt: {original_prompt}\n\nManim script:\n{manim_script}\n\nCreate educational narration for this animation:"
                }
            ]
        )
        
        content = message.content[0]
        narration_text = extract_text_from_content(content)
        return narration_text.strip()
        
    except Exception as e:
        raise Exception(f"Failed to extract narration: {str(e)}")


def get_voice_for_language(language: str, user_voice: str = "alloy") -> str:
    """
    Select the most appropriate TTS voice for the detected language.
    Honor an explicit user-selected voice when provided.
    """
    # Respect explicit voice selections (non-default)
    if user_voice != "alloy":
        logger.info(f"Using caller-provided voice: {user_voice}")
        return user_voice
    
    # Otherwise map language to curated defaults
    language_to_voice = {
        'en': 'alloy',      # English - neutral and clear
        'es': 'nova',       # Spanish - warm female tone
        'fr': 'shimmer',    # French - bright, crisp delivery
        'de': 'onyx',       # German - confident male tone
        'it': 'nova',       # Italian - expressive female tone
        'pt': 'nova',       # Portuguese - expressive female tone
        'ru': 'echo',       # Russian - deep male tone
        'ja': 'shimmer',    # Japanese - light precise voice
        'ko': 'shimmer',    # Korean - light precise voice
        'zh': 'nova',       # Chinese - balanced female voice
        'ar': 'fable',      # Arabic - resonant male tone
        'hi': 'nova'        # Hindi - balanced female voice
    }
    
    selected_voice = language_to_voice.get(language, 'alloy')
    logger.info(f"Auto-selected voice '{selected_voice}' for language '{language}'")
    return selected_voice


async def generate_tts_audio(text: str, animation_id: str, voice: str = "alloy", language: str = "en") -> str:
    """
    Generate TTS audio using OpenAI's TTS API.
    """
    try:
        client = get_openai_client()
        
        # Validate input text
        if not text or len(text.strip()) < 3:
            logger.warning(f"TTS input text is too short: '{text}', using fallback")
            text = "Educational animation content."
        
        text = text.strip()
        
        # Pick the most natural-sounding voice for the language
        selected_voice = get_voice_for_language(language, voice)
        
        logger.info(f"Generating TTS audio - language: {language}, voice: {selected_voice}, text: '{text[:100]}...'")
        
        # Create TTS audio with slower, clearer speech for education
        response = client.audio.speech.create(
            model="tts-1",
            voice=selected_voice,
            input=text,
            response_format="mp3",
            speed=0.85  # Slower speed for better comprehension (0.25 to 4.0, default 1.0)
        )
        
        # Save audio file
        audio_path = f"temp_output/{animation_id}_audio.mp3"
        os.makedirs(os.path.dirname(audio_path), exist_ok=True)
        
        with open(audio_path, "wb") as f:
            f.write(response.content)
        
        logger.info(f"TTS audio generated: {audio_path}")
        return audio_path
        
    except Exception as e:
        raise Exception(f"Failed to generate TTS audio: {str(e)}")
