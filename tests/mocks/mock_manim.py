"""
Mock Manim execution for testing.

This module provides mock video generation without actually running Manim,
which significantly speeds up tests.
"""

import os
import subprocess

# Minimal valid MP4 file header (enough to be recognized as MP4)
MP4_HEADER = b'\x00\x00\x00\x20\x66\x74\x79\x70\x69\x73\x6f\x6d\x00\x00\x02\x00'
MP4_HEADER += b'\x69\x73\x6f\x6d\x69\x73\x6f\x32\x61\x76\x63\x31\x6d\x70\x34\x31'

# Extended mock MP4 data
MOCK_MP4_DATA = MP4_HEADER + b'\x00' * 10000  # ~10KB fake MP4


def create_mock_video_file(filepath: str, duration: float = 5.0) -> str:
    """
    Create a mock video file on disk for testing.

    Args:
        filepath: Path where to save the mock video file
        duration: Simulated video duration in seconds (affects file size)

    Returns:
        The filepath of the created video
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # File size roughly proportional to duration
    multiplier = max(1, int(duration / 5))
    video_data = MOCK_MP4_DATA * multiplier

    with open(filepath, "wb") as f:
        f.write(video_data)

    return filepath


async def mock_execute_manim_script(
    script_path: str,
    video_id: str,
    resolution: str = "m"
) -> str:
    """
    Mock Manim script execution that creates a fake video file.

    Args:
        script_path: Path to the Manim script file
        video_id: Unique ID for the video
        resolution: Video resolution (l, m, h, p, k)

    Returns:
        Path to the generated video file
    """
    # Simulate different output directories based on resolution
    quality_map = {
        "l": "480p15",
        "m": "720p30",
        "h": "1080p60",
        "p": "1080p60",
        "k": "2160p60"
    }
    quality = quality_map.get(resolution, "720p30")

    output_dir = f"temp_output/{quality}"
    os.makedirs(output_dir, exist_ok=True)

    video_path = f"{output_dir}/{video_id}.mp4"

    # Create mock video file
    create_mock_video_file(video_path, duration=10.0)

    return video_path


class MockManimProcess:
    """Mock subprocess for Manim execution."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout.encode()
        self.stderr = stderr.encode()


def mock_subprocess_run_success(*args, **kwargs):
    """Mock subprocess.run that simulates successful Manim execution."""
    return MockManimProcess(
        returncode=0,
        stdout="Manim Community v0.18.0\nFile ready at temp_output/video.mp4",
        stderr=""
    )


def mock_subprocess_run_failure(*args, **kwargs):
    """Mock subprocess.run that simulates failed Manim execution."""
    return MockManimProcess(
        returncode=1,
        stdout="",
        stderr="NameError: name 'UndefinedObject' is not defined"
    )


def patch_manim_execution(monkeypatch, should_fail: bool = False):
    """
    Patch Manim execution for testing.

    Args:
        monkeypatch: pytest monkeypatch fixture
        should_fail: Whether Manim should fail
    """
    if should_fail:
        monkeypatch.setattr(subprocess, "run", mock_subprocess_run_failure)
    else:
        monkeypatch.setattr(subprocess, "run", mock_subprocess_run_success)

    # Also patch the execute_manim_script function
    from services import video_processor
    monkeypatch.setattr(
        video_processor,
        "execute_manim_script",
        mock_execute_manim_script
    )
