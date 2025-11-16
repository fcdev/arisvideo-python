"""
Mock OpenAI TTS client for testing.

This module provides mock audio data for TTS generation
without making actual API calls.
"""

import os

# Minimal valid MP3 file header (MPEG-1 Layer 3)
MOCK_MP3_HEADER = b'\xff\xfb\x90\x00' + b'\x00' * 416

# Extended mock MP3 data for testing
MOCK_MP3_DATA = MOCK_MP3_HEADER * 100  # ~40KB fake MP3


def get_mock_audio_data(text: str, voice: str = "alloy") -> bytes:
    """
    Generate mock audio data for testing.

    Args:
        text: The text to "convert" to audio
        voice: The voice to use (ignored in mock)

    Returns:
        Mock MP3 audio bytes
    """
    # In a mock, we don't actually generate audio, just return fake data
    # The length could be proportional to text length for realism
    multiplier = max(1, len(text) // 100)
    return MOCK_MP3_DATA * multiplier


def get_mock_timing_analysis(text: str) -> dict:
    """
    Generate mock timing analysis data.

    Args:
        text: The text to analyze

    Returns:
        Mock timing analysis dictionary
    """
    # Estimate duration based on text length (average reading speed)
    word_count = len(text.split())
    duration = word_count / 2.5  # Assuming ~150 words per minute

    return {
        "total_duration": duration,
        "segments": [
            {
                "text": text,
                "start": 0.0,
                "end": duration
            }
        ]
    }


def create_mock_audio_file(filepath: str, text: str = "") -> None:
    """
    Create a mock audio file on disk for testing.

    Args:
        filepath: Path where to save the mock audio file
        text: The text content (affects file size)
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    audio_data = get_mock_audio_data(text)
    with open(filepath, "wb") as f:
        f.write(audio_data)


class MockOpenAIResponse:
    """Mock OpenAI API response for TTS."""

    def __init__(self, audio_data: bytes):
        self.content = audio_data

    def iter_bytes(self, chunk_size: int = 1024):
        """Iterate over audio bytes in chunks."""
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]


def create_mock_openai_client():
    """
    Create a mock OpenAI client for testing.

    Returns:
        Mock client object with audio.speech.create method
    """
    from unittest.mock import Mock

    mock_client = Mock()
    mock_client.audio = Mock()
    mock_client.audio.speech = Mock()

    def mock_create(model=None, voice=None, input=None, **kwargs):
        return MockOpenAIResponse(get_mock_audio_data(input or "", voice or "alloy"))

    mock_client.audio.speech.create = mock_create

    return mock_client
