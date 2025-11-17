"""
Manim Script Modification Service

This service provides utilities for modifying generated Manim scripts to adjust
timing based on actual audio duration measurements. It enables two-pass rendering
where the script is adjusted after audio generation to ensure perfect synchronization.
"""

import re
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def calculate_wait_adjustments(
    timing_segments: List[Dict],
    audio_segments: List[Dict],
    threshold: float = 0.1
) -> List[Dict]:
    """
    Calculate required wait time adjustments by comparing video timing with actual audio durations.

    Args:
        timing_segments: List of timing segments from extract_animation_timing()
                        [{start_time, end_time, description, content}, ...]
        audio_segments: List of audio segment metadata from create_synchronized_audio()
                       [{segment_index, planned_start, planned_end, actual_start,
                         actual_end, audio_duration, text}, ...]
        threshold: Minimum duration mismatch (in seconds) to trigger adjustment

    Returns:
        List of adjustments: [{segment_index, wait_duration, video_duration, audio_duration}, ...]
    """
    adjustments = []

    logger.info("Analyzing timing mismatches between video and audio segments")

    for i, (timing_seg, audio_seg) in enumerate(zip(timing_segments, audio_segments)):
        # Calculate durations
        video_duration = timing_seg['end_time'] - timing_seg['start_time']
        audio_duration = audio_seg.get('audio_duration', audio_seg['actual_end'] - audio_seg['actual_start'])

        # Calculate mismatch
        duration_diff = audio_duration - video_duration

        # Log the comparison
        logger.debug(
            "Segment %d: video=%.2fs, audio=%.2fs, diff=%.2fs",
            i, video_duration, audio_duration, duration_diff
        )

        # If audio is longer than video by more than threshold, add wait time
        if duration_diff > threshold:
            wait_duration = duration_diff
            adjustments.append({
                'segment_index': i,
                'wait_duration': round(wait_duration, 2),
                'video_duration': round(video_duration, 2),
                'audio_duration': round(audio_duration, 2),
                'segment_description': timing_seg.get('description', f'Segment {i}')
            })
            logger.info(
                "Segment %d (%s): Adding %.2fs wait (video: %.2fs, audio: %.2fs)",
                i, timing_seg.get('description', 'Unknown'), wait_duration,
                video_duration, audio_duration
            )

    if adjustments:
        total_added_time = sum(adj['wait_duration'] for adj in adjustments)
        logger.info(
            "Found %d segments needing adjustment, total added time: %.2fs",
            len(adjustments), total_added_time
        )
    else:
        logger.info("No timing adjustments needed - all segments within threshold")

    return adjustments


def inject_wait_times(
    script: str,
    adjustments: List[Dict],
    timing_segments: List[Dict]
) -> str:
    """
    Inject self.wait() calls into a Manim script to match audio duration.

    This function analyzes the script structure and adds wait() calls at the end
    of each segment that needs timing adjustment.

    Args:
        script: Original Manim script code
        adjustments: List of timing adjustments from calculate_wait_adjustments()
        timing_segments: Original timing segments to help locate insertion points

    Returns:
        Modified script with wait() calls injected
    """
    if not adjustments:
        logger.info("No adjustments to inject")
        return script

    logger.info("Injecting %d wait() calls into Manim script", len(adjustments))

    # Split script into lines for modification
    lines = script.split('\n')

    # Find the construct method
    construct_start = None
    for i, line in enumerate(lines):
        if re.search(r'def\s+construct\s*\(', line):
            construct_start = i
            break

    if construct_start is None:
        logger.error("Could not find construct() method in script")
        return script

    # Track current indentation level (usually 8 spaces or 2 tabs)
    base_indent = None
    for i in range(construct_start + 1, len(lines)):
        if lines[i].strip() and not lines[i].strip().startswith('#'):
            # Find first non-comment, non-empty line after construct
            base_indent = len(lines[i]) - len(lines[i].lstrip())
            break

    if base_indent is None:
        base_indent = 8  # Default to 8 spaces

    indent = ' ' * base_indent

    # Strategy: Find segment boundaries by analyzing timing_segments content
    # and matching it with code sections

    # Create a mapping of adjustments by segment index
    adjustment_map = {adj['segment_index']: adj for adj in adjustments}

    # Insert wait calls in reverse order to preserve line numbers
    # We'll insert after each segment based on content matching
    modifications_made = 0

    for seg_idx in sorted(adjustment_map.keys(), reverse=True):
        adjustment = adjustment_map[seg_idx]
        wait_duration = adjustment['wait_duration']

        # Find the best insertion point for this segment
        # Look for the end of the segment by finding self.play() or self.wait() calls
        # and inserting after them

        # Simple heuristic: Insert wait after every (segment_index + 1) * play/wait calls
        # This assumes segments roughly correspond to play/wait groupings

        insertion_line = _find_segment_end(
            lines,
            construct_start,
            seg_idx,
            len(timing_segments)
        )

        if insertion_line is not None:
            # Insert wait() call
            wait_line = f"{indent}self.wait({wait_duration})  # Audio sync adjustment"
            lines.insert(insertion_line + 1, wait_line)
            modifications_made += 1
            logger.debug(
                "Injected wait(%.2fs) after line %d for segment %d",
                wait_duration, insertion_line, seg_idx
            )
        else:
            logger.warning(
                "Could not find insertion point for segment %d adjustment",
                seg_idx
            )

    if modifications_made > 0:
        logger.info("Successfully injected %d wait() calls", modifications_made)

    return '\n'.join(lines)


def _find_segment_end(
    lines: List[str],
    construct_start: int,
    segment_index: int,
    total_segments: int
) -> Optional[int]:
    """
    Find the line number where a segment ends in the construct method.

    Args:
        lines: Script lines
        construct_start: Line number where construct() method starts
        segment_index: Index of the segment to find (0-based)
        total_segments: Total number of segments

    Returns:
        Line number where segment ends, or None if not found
    """
    # Find all self.play() and self.wait() calls in construct method
    play_wait_lines = []

    for i in range(construct_start + 1, len(lines)):
        line = lines[i].strip()

        # Stop at end of method (dedent or new method definition)
        if line.startswith('def ') and i > construct_start:
            break

        # Find self.play() or self.wait() calls
        if re.search(r'self\.(play|wait)\s*\(', line):
            play_wait_lines.append(i)

    if not play_wait_lines:
        logger.warning("No play/wait calls found in construct method")
        return None

    # Divide play/wait calls into segments
    # Assumption: segments are roughly evenly distributed
    calls_per_segment = max(1, len(play_wait_lines) // total_segments)

    # Find the last play/wait call for this segment
    segment_end_index = min(
        (segment_index + 1) * calls_per_segment - 1,
        len(play_wait_lines) - 1
    )

    # Adjust for last segment to include all remaining calls
    if segment_index == total_segments - 1:
        segment_end_index = len(play_wait_lines) - 1

    return play_wait_lines[segment_end_index]


def analyze_script_structure(script: str) -> Dict:
    """
    Analyze the structure of a Manim script for debugging purposes.

    Args:
        script: Manim script code

    Returns:
        Dictionary with structure information: {
            'class_name': str,
            'construct_line': int,
            'play_count': int,
            'wait_count': int,
            'total_lines': int
        }
    """
    lines = script.split('\n')

    info = {
        'class_name': None,
        'construct_line': None,
        'play_count': 0,
        'wait_count': 0,
        'total_lines': len(lines)
    }

    for i, line in enumerate(lines):
        # Find class name
        class_match = re.search(r'class\s+(\w+)\s*\(', line)
        if class_match:
            info['class_name'] = class_match.group(1)

        # Find construct method
        if re.search(r'def\s+construct\s*\(', line):
            info['construct_line'] = i

        # Count play and wait calls
        if 'self.play(' in line:
            info['play_count'] += 1
        if 'self.wait(' in line:
            info['wait_count'] += 1

    return info


def validate_modified_script(script: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that a modified script is syntactically correct.

    Args:
        script: Modified Manim script

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        # Try to compile the script
        compile(script, '<string>', 'exec')
        return True, None
    except SyntaxError as e:
        error_msg = f"Syntax error at line {e.lineno}: {e.msg}"
        logger.error("Script validation failed: %s", error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Validation error: {str(e)}"
        logger.error("Script validation failed: %s", error_msg)
        return False, error_msg
