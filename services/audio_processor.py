"""
Audio processing service for TTS generation and audio synchronization.
"""

import os
import re
import asyncio
import shutil
from typing import List, Dict, Any, Optional, Tuple
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
            model="claude-sonnet-4-5-20250929",
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
            model="claude-sonnet-4-5-20250929",
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
        def extract_json_array(text: str) -> str:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned[3:].lstrip()
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].lstrip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].rstrip()
            cleaned = cleaned.strip()
            if cleaned and cleaned[0] not in "[{":
                import re
                match = re.search(r"(\[[\s\S]+\])", cleaned)
                if match:
                    cleaned = match.group(1).strip()
            return cleaned or text
        
        narration_payload = extract_json_array(narration_text)
        try:
            narration_segments = json.loads(narration_payload)
            
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
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Create audio with precise timing using silence padding.

    Returns:
        Tuple of (audio_path, segment_metadata) where segment_metadata contains
        timing information for each segment including actual audio durations.
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
            
            # Measure actual spoken duration
            actual_duration = await get_audio_duration(segment_path)
            if actual_duration <= 0:
                actual_duration = max(segment.get("end_time", 0) - segment.get("start_time", 0), 1.0)

            start_time = float(segment.get("start_time", 0.0))
            planned_end = segment.get("end_time")
            planned_end = float(planned_end) if planned_end is not None else start_time + actual_duration

            # Calculate planned video segment duration
            planned_duration = planned_end - start_time

            # BIDIRECTIONAL MATCHING: Pad audio with silence if video segment is longer
            if actual_duration < planned_duration - 0.1:  # 100ms threshold
                silence_needed = planned_duration - actual_duration
                logger.info(
                    f"Segment {i}: Video ({planned_duration:.2f}s) longer than audio ({actual_duration:.2f}s), "
                    f"padding with {silence_needed:.2f}s silence"
                )

                # Create padded audio file with silence appended
                padded_path = f"temp_output/{animation_id}_segment_{i}_padded.mp3"
                silence_duration_ms = int(silence_needed * 1000)

                # Use FFmpeg to append silence
                ffmpeg_path = shutil.which("ffmpeg") or os.path.expanduser("~/bin/ffmpeg")
                pad_cmd = [
                    ffmpeg_path,
                    "-i", segment_path,
                    "-f", "lavfi",
                    "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={silence_needed}",
                    "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[out]",
                    "-map", "[out]",
                    "-c:a", "mp3",
                    "-y",
                    padded_path
                ]

                process = await asyncio.create_subprocess_exec(
                    *pad_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await process.communicate()

                if process.returncode == 0:
                    # Replace original with padded version
                    os.remove(segment_path)
                    segment_path = padded_path
                    actual_duration = planned_duration
                    logger.debug(f"Segment {i} padded successfully to {actual_duration:.2f}s")
                else:
                    logger.warning(f"Segment {i} padding failed, using original audio")

            actual_end = start_time + actual_duration
            adjusted_end = max(planned_end, actual_end)

            if adjusted_end > planned_end + 0.05:
                logger.debug(
                    "Segment %d: Audio longer than video, will need wait() in video script "
                    "(planned %.2fs, actual %.2fs)",
                    i,
                    planned_end - start_time,
                    actual_duration,
                )

            audio_segments.append({
                "path": segment_path,
                "start_time": start_time,  # Original planned timing
                "end_time": adjusted_end,
                "duration": actual_duration,
                "text": text,
                "planned_start": start_time,  # Store original timing for reference
                "planned_end": adjusted_end
            })

        # CRITICAL FIX: Recalculate timing to be cumulative (sequential) to prevent audio overlay
        # This ensures segments play one after another, never simultaneously
        cumulative_time = 0.0
        for i, segment in enumerate(audio_segments):
            # Update timing to be sequential based on actual audio durations
            segment["start_time"] = cumulative_time
            segment["end_time"] = cumulative_time + segment["duration"]
            cumulative_time = segment["end_time"]

            logger.debug(
                "Segment %d cumulative timing: %.2fs-%.2fs (planned: %.2fs-%.2fs)",
                i, segment["start_time"], segment["end_time"],
                segment["planned_start"], segment["planned_end"]
            )

        logger.info(f"Total cumulative audio duration: {cumulative_time:.2f}s")

        # Combine segments with precise timing using FFmpeg
        final_audio_path = f"temp_output/{animation_id}_synced_audio.mp3"
        await combine_audio_segments(audio_segments, final_audio_path)

        # Prepare segment metadata for timing adjustment
        # planned_start/end = original video animation timing from Claude AI
        # actual_start/end = cumulative sequential audio timing (prevents overlay)
        segment_metadata = []
        for i, segment in enumerate(audio_segments):
            segment_metadata.append({
                "segment_index": i,
                "planned_start": segment["planned_start"],  # Original video timing
                "planned_end": segment["planned_end"],      # Original video timing
                "actual_start": segment["start_time"],      # Cumulative audio timing
                "actual_end": segment["end_time"],          # Cumulative audio timing
                "audio_duration": segment["duration"],
                "text": segment["text"]
            })

        # Clean up segment files
        for segment in audio_segments:
            try:
                os.remove(segment["path"])
            except:
                pass

        return final_audio_path, segment_metadata
        
    except Exception as e:
        raise Exception(f"Failed to create synchronized audio: {str(e)}")


async def combine_audio_segments(segments: List[Dict[str, Any]], output_path: str) -> None:
    """
    Combine audio segments sequentially with silence gaps using FFmpeg concat.

    CRITICAL FIX: This function now uses sequential concatenation instead of amix
    to prevent audio overlay issues. Segments are played one after another with
    silence gaps, never simultaneously.
    """
    try:
        if len(segments) == 0:
            raise Exception("No audio segments to combine")

        logger.info(f"Combining {len(segments)} audio segments sequentially (no overlay)")

        # Use sequential concatenation approach (NOT amix which causes overlay)
        # This ensures segments never play simultaneously
        await create_simple_timed_audio(segments, output_path)

        logger.info(f"Sequential audio combination complete: {output_path}")

    except Exception as e:
        logger.error(f"Audio combination failed: {str(e)}")
        raise Exception(f"Failed to combine audio segments: {str(e)}")


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


async def generate_subtitle_file_from_segments(
    narration_segments: list[dict],
    animation_id: str,
    format: str = "srt"
) -> str:
    """
    Generate subtitle file from narration segments with precise timing.

    Args:
        narration_segments: List of segments with start_time, end_time, text
        animation_id: Video ID for file naming
        format: 'srt' or 'vtt' (default: 'srt')

    Returns:
        Path to generated subtitle file
    """
    try:
        subtitle_path = f"temp_output/{animation_id}_subtitles.{format}"
        os.makedirs(os.path.dirname(subtitle_path), exist_ok=True)

        with open(subtitle_path, "w", encoding="utf-8") as f:
            if format == "vtt":
                f.write("WEBVTT\n\n")

            for i, segment in enumerate(narration_segments):
                start_time = segment["start_time"]
                end_time = segment["end_time"]
                text = segment["text"]

                # Format timestamps
                if format == "srt":
                    # SRT format: HH:MM:SS,mmm --> HH:MM:SS,mmm
                    start_srt = format_srt_time(start_time)
                    end_srt = format_srt_time(end_time)

                    f.write(f"{i+1}\n")
                    f.write(f"{start_srt} --> {end_srt}\n")
                    f.write(f"{text}\n\n")
                else:
                    # VTT format: HH:MM:SS.mmm --> HH:MM:SS.mmm
                    start_vtt = format_vtt_time(start_time)
                    end_vtt = format_vtt_time(end_time)

                    f.write(f"{start_vtt} --> {end_vtt}\n")
                    f.write(f"{text}\n\n")

        logger.info(f"Generated {format.upper()} subtitle file: {subtitle_path}")
        return subtitle_path

    except Exception as e:
        raise Exception(f"Failed to generate subtitle file: {str(e)}")


def format_srt_time(seconds: float) -> str:
    """Format time in SRT format: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_vtt_time(seconds: float) -> str:
    """Format time in VTT format: HH:MM:SS.mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


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
            model="claude-sonnet-4-5-20250929",
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
