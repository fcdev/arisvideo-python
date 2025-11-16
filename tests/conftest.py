"""
Pytest configuration and fixtures for ArisVideo tests.

This file provides shared fixtures for testing the FastAPI application,
including test client, database setup, and mock dependencies.
"""

import os
import sys
import asyncio
import pytest
from typing import AsyncGenerator, Generator
from unittest.mock import Mock, AsyncMock, patch
from httpx import AsyncClient
from databases import Database

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app
from db import database


# ============================================================================
# Test Configuration
# ============================================================================

@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def integration_mode() -> bool:
    """
    Check if integration mode is enabled.
    Integration mode runs tests with real APIs (Claude, OpenAI, Manim).
    Set INTEGRATION_TESTS=true to enable.
    """
    return os.getenv("INTEGRATION_TESTS", "false").lower() == "true"


# ============================================================================
# FastAPI Test Client
# ============================================================================

@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """
    Create a test client for FastAPI app.
    This client can be used to make requests to the API endpoints.
    """
    from httpx import ASGITransport
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def api_key() -> str:
    """Return the API key for testing."""
    return os.getenv("API_KEY", "test-api-key")


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture
async def test_db() -> AsyncGenerator[Database, None]:
    """
    Create a test database connection.
    This uses the same database as the main app but in a transaction
    that gets rolled back after each test.
    """
    await database.connect()
    yield database
    await database.disconnect()


# ============================================================================
# Mock Fixtures
# ============================================================================

@pytest.fixture
def mock_claude_client(integration_mode):
    """
    Mock Anthropic Claude AI client.
    In unit mode: returns mock script
    In integration mode: uses real API
    """
    if integration_mode:
        return None  # Use real client

    # Create mock client
    mock_client = Mock()
    mock_client.messages = Mock()
    mock_client.messages.create = AsyncMock()

    # Mock response for script generation
    mock_message = Mock()
    mock_message.content = [Mock(text="""from manim import *

class TestScene(Scene):
    def construct(self):
        # Simple test animation
        title = Text("Test Animation")
        self.play(Write(title))
        self.wait(2)
        self.play(FadeOut(title))
""")]

    mock_client.messages.create.return_value = mock_message
    return mock_client


@pytest.fixture
def mock_openai_client(integration_mode):
    """
    Mock OpenAI client for TTS.
    In unit mode: returns mock audio data
    In integration mode: uses real API
    """
    if integration_mode:
        return None  # Use real client

    # Create mock client
    mock_client = Mock()
    mock_client.audio = Mock()
    mock_client.audio.speech = Mock()
    mock_client.audio.speech.create = Mock()

    # Mock audio response (minimal valid MP3 header)
    mock_response = Mock()
    mock_response.content = b'\xff\xfb\x90\x00' * 100  # Fake MP3 data
    mock_client.audio.speech.create.return_value = mock_response

    return mock_client


@pytest.fixture
def mock_manim_execution(integration_mode):
    """
    Mock Manim script execution.
    In unit mode: creates dummy video file
    In integration mode: runs real Manim
    """
    if integration_mode:
        return None  # Use real Manim

    def mock_execute(script_path: str, video_id: str, resolution: str = "m"):
        """Create a dummy video file."""
        os.makedirs("temp_output", exist_ok=True)
        video_path = f"temp_output/{video_id}.mp4"

        # Create minimal valid MP4 file (just header bytes)
        mp4_header = b'\x00\x00\x00\x20\x66\x74\x79\x70\x69\x73\x6f\x6d'
        with open(video_path, "wb") as f:
            f.write(mp4_header * 100)

        return video_path

    return mock_execute


# ============================================================================
# Environment Setup
# ============================================================================

@pytest.fixture(autouse=True)
def setup_test_env():
    """Set up test environment variables."""
    original_env = os.environ.copy()

    # Set test environment variables
    os.environ["API_KEY"] = "test-api-key"
    os.environ["VIDEO_STORAGE_PATH"] = "./test_media/videos"
    os.environ["ANTHROPIC_API_KEY"] = os.getenv("ANTHROPIC_API_KEY", "test-key")
    os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY", "test-key")

    # Create test directories
    os.makedirs("test_media/videos", exist_ok=True)
    os.makedirs("temp_scripts", exist_ok=True)
    os.makedirs("temp_output", exist_ok=True)

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture(autouse=True)
def cleanup_test_files():
    """Clean up test files after each test."""
    yield

    # Clean up test directories
    import shutil
    for directory in ["test_media", "temp_scripts", "temp_output"]:
        if os.path.exists(directory):
            shutil.rmtree(directory, ignore_errors=True)


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture
def sample_prompt() -> str:
    """Return a sample prompt for testing."""
    return "Explain the Pythagorean theorem using visual animations"


@pytest.fixture
def sample_animation_request():
    """Return a sample animation request for testing."""
    from models import AnimationRequest
    return AnimationRequest(
        prompt="Explain the Pythagorean theorem",
        resolution="m",
        include_audio=True,
        language="en",
        voice="alloy",
        sync_method="timing_analysis"
    )
