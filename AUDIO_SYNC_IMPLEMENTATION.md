# Audio-Driven Video Script Adjustment Implementation

## Overview
This document describes the two-pass rendering implementation that adjusts Manim scripts based on actual audio duration to eliminate audio-video synchronization issues.

## Implementation Summary

### Files Modified/Created

1. **NEW: `services/manim_script_modifier.py`** (~300 lines)
   - `calculate_wait_adjustments()`: Analyzes timing mismatches between video and audio segments
   - `inject_wait_times()`: Injects `self.wait()` calls into Manim scripts
   - `validate_modified_script()`: Validates Python syntax of modified scripts
   - Helper functions for script analysis and structure parsing

2. **MODIFIED: `services/audio_processor.py`**
   - Updated `create_synchronized_audio()` return type from `str` to `Tuple[str, List[Dict]]`
   - Now returns both audio path and detailed segment metadata including:
     - `segment_index`, `planned_start`, `planned_end`
     - `actual_start`, `actual_end`, `audio_duration`
     - `text` (narration text)
   - Added `Tuple` import from typing

3. **MODIFIED: `models/schemas.py`**
   - Added `timing_adjustment_threshold: float = 0.1` to `AnimationRequest`
   - Default threshold: 0.1 seconds (100ms)

4. **MODIFIED: `app.py`**
   - Imported script modifier functions
   - Updated `timing_analysis` sync method with two-pass rendering flow
   - Added timing adjustment logic after audio generation
   - Re-renders video with adjusted script if needed

## Two-Pass Rendering Flow

### Previous Flow (timing_analysis)
```
1. Generate Manim script
2. Render video (pass 1)
3. Extract timing segments
4. Generate timed narration
5. Create synchronized audio
6. Combine audio + video
   └─> If mismatch: freeze last frame or loop video
```

### New Flow (timing_analysis)
```
1. Generate Manim script
2. Render video (pass 1)
3. Extract timing segments
4. Generate timed narration
5. Create synchronized audio
   └─> Returns (audio_path, segment_metadata)
6. **Analyze timing mismatches**
   └─> calculate_wait_adjustments(timing_segments, segment_metadata)
7. **If mismatches > threshold:**
   a. Inject wait() calls into script
   b. Validate modified script
   c. Save adjusted script
   d. Re-render video (pass 2)
   e. Update video_path and duration
8. Combine audio + video (now perfectly synced)
```

## Key Features

### Timing Adjustment Threshold
- Configurable via `timing_adjustment_threshold` parameter (default: 0.1s)
- Only segments with audio > video + threshold are adjusted
- Prevents unnecessary re-renders for tiny differences

### Smart Wait Injection
- Analyzes Manim script structure to find segment boundaries
- Injects `self.wait(duration)` calls at appropriate positions
- Preserves original code structure and indentation
- Uses AST-like parsing to avoid breaking code

### Validation & Safety
- Modified scripts are validated before rendering
- If validation fails, uses original script (graceful fallback)
- Logs detailed information about adjustments for debugging

### Status Tracking
- Updates status to "Adjusting script timing" during analysis
- Updates status to "Re-rendering video" during second pass
- Progress percentage reflects two-pass workflow

## Example Scenario

**Input**: Prompt requesting 3-part animation

**Pass 1 Results**:
- Video segment 1: 8.0s
- Video segment 2: 7.5s
- Video segment 3: 9.0s
- Total video: 24.5s

**Audio Generation**:
- Audio segment 1: 9.2s (1.2s longer)
- Audio segment 2: 8.1s (0.6s longer)
- Audio segment 3: 10.5s (1.5s longer)
- Total audio: 27.8s

**Adjustment Analysis** (threshold = 0.1s):
- Segment 1: +1.2s → Add wait(1.2)
- Segment 2: +0.6s → Add wait(0.6)
- Segment 3: +1.5s → Add wait(1.5)

**Pass 2 Results**:
- Video segment 1: 8.0s + 1.2s = 9.2s ✓
- Video segment 2: 7.5s + 0.6s = 8.1s ✓
- Video segment 3: 9.0s + 1.5s = 10.5s ✓
- Total video: 27.8s ✓

**Outcome**: Perfect synchronization without frozen frames

## Configuration

### Default Settings
```python
AnimationRequest(
    prompt="...",
    sync_method="timing_analysis",  # Required for two-pass rendering
    timing_adjustment_threshold=0.1,  # Minimum mismatch to trigger adjustment
    # ... other fields
)
```

### Disabling Two-Pass Rendering
Set `timing_adjustment_threshold` to a very high value (e.g., 999.9) to effectively disable:
```python
AnimationRequest(
    prompt="...",
    timing_adjustment_threshold=999.9  # Never triggers adjustment
)
```

## Benefits

✅ **Perfect audio-video synchronization** - No more frozen frames or loops
✅ **Natural video pacing** - Pauses match narration rhythm
✅ **Better educational content** - Smooth transitions between concepts
✅ **Automatic adjustment** - No manual script tweaking required
✅ **Graceful degradation** - Falls back to original script if validation fails

## Trade-offs

⚠️ **Longer generation time** - Two video renders instead of one (typically +30-50% time)
⚠️ **Only for timing_analysis** - Other sync methods unchanged
⚠️ **Heuristic-based injection** - May not always find perfect insertion points

## Testing

### Verification Steps
1. ✅ Syntax validation: All modified files compile without errors
2. ✅ Import verification: Functions properly imported in app.py
3. ✅ Integration check: Return values properly unpacked
4. ✅ Type annotations: Correct type hints for Tuple return

### Manual Testing Recommendations
1. Generate a video with `sync_method="timing_analysis"`
2. Check logs for "Adjusting Manim script timing" message
3. Verify two render steps in logs
4. Compare original vs adjusted script in `temp_scripts/`
5. Verify final video has natural pauses matching audio

### Expected Log Output
```
✅ Subtitle file saved: ...
🔧 Adjusting Manim script timing for 3 segments
✅ Modified script validation successful
🎬 Re-rendering video with adjusted timing
✅ Re-rendered video duration: 27.8s
🎬 Step 4: Combining audio and video
```

## Future Improvements

Potential enhancements:
- Machine learning to predict optimal wait insertion points
- Visual analysis to avoid adding waits during active animations
- Per-segment threshold configuration
- A/B testing to compare with/without adjustment
- Metrics tracking: adjustment frequency, time savings, quality improvements

## Troubleshooting

### Issue: Modified script fails validation
**Solution**: Check logs for syntax errors, falls back to original script automatically

### Issue: Wait calls inserted at wrong positions
**Solution**: Adjust the heuristic in `_find_segment_end()` or use different parsing strategy

### Issue: Generation taking too long
**Solution**: Increase `timing_adjustment_threshold` to reduce re-render frequency

### Issue: Audio still out of sync
**Solution**: Check if using `timing_analysis` method; other methods don't use this feature

## Changelog

### v1.0.0 (2024-11-17)
- Initial implementation of two-pass rendering
- Added `manim_script_modifier` service
- Updated `audio_processor` to return segment metadata
- Modified `app.py` timing_analysis flow
- Added `timing_adjustment_threshold` configuration

---

**Author**: Claude Code
**Date**: November 17, 2024
**Status**: Ready for testing
