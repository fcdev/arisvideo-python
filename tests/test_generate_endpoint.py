"""
Tests for the /generate endpoint.

This module tests the video generation endpoint including:
- Request validation
- API key authentication
- Background task creation
- Database record creation
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_generate_with_valid_prompt(client: AsyncClient, api_key: str, test_db):
    """Test /generate endpoint with a valid prompt."""
    response = await client.post(
        "/generate",
        json={
            "prompt": "Explain the Pythagorean theorem",
            "resolution": "m",
            "include_audio": True,
            "language": "en"
        },
        headers={"X-API-Key": api_key}
    )

    assert response.status_code == 200
    data = response.json()

    assert "video_id" in data
    assert data["status"] == "processing"
    assert data["message"] == "Video generation started successfully"
    assert len(data["video_id"]) > 0


@pytest.mark.asyncio
async def test_generate_without_api_key(client: AsyncClient):
    """Test /generate endpoint without API key (should fail)."""
    response = await client.post(
        "/generate",
        json={
            "prompt": "Test prompt",
            "resolution": "m"
        }
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_generate_with_invalid_api_key(client: AsyncClient):
    """Test /generate endpoint with invalid API key."""
    response = await client.post(
        "/generate",
        json={
            "prompt": "Test prompt",
            "resolution": "m"
        },
        headers={"X-API-Key": "wrong-key"}
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_generate_with_empty_prompt(client: AsyncClient, api_key: str):
    """Test /generate endpoint with empty prompt (should fail)."""
    response = await client.post(
        "/generate",
        json={
            "prompt": "",
            "resolution": "m"
        },
        headers={"X-API-Key": api_key}
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_generate_with_missing_prompt(client: AsyncClient, api_key: str):
    """Test /generate endpoint without prompt field."""
    response = await client.post(
        "/generate",
        json={
            "resolution": "m"
        },
        headers={"X-API-Key": api_key}
    )

    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_generate_with_invalid_resolution(client: AsyncClient, api_key: str):
    """Test /generate endpoint with invalid resolution."""
    response = await client.post(
        "/generate",
        json={
            "prompt": "Test prompt",
            "resolution": "invalid"
        },
        headers={"X-API-Key": api_key}
    )

    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_generate_with_all_parameters(client: AsyncClient, api_key: str, test_db):
    """Test /generate endpoint with all optional parameters."""
    response = await client.post(
        "/generate",
        json={
            "prompt": "Explain quantum physics",
            "resolution": "h",
            "include_audio": True,
            "language": "es",
            "voice": "nova",
            "sync_method": "timing_analysis"
        },
        headers={"X-API-Key": api_key}
    )

    assert response.status_code == 200
    data = response.json()

    assert "video_id" in data
    assert data["status"] == "processing"


@pytest.mark.asyncio
async def test_generate_without_audio(client: AsyncClient, api_key: str, test_db):
    """Test /generate endpoint with audio disabled."""
    response = await client.post(
        "/generate",
        json={
            "prompt": "Show a circle",
            "resolution": "l",
            "include_audio": False
        },
        headers={"X-API-Key": api_key}
    )

    assert response.status_code == 200
    data = response.json()

    assert "video_id" in data
    assert data["status"] == "processing"


@pytest.mark.asyncio
async def test_generate_creates_database_record(client: AsyncClient, api_key: str, test_db):
    """Test that /generate creates a record in the database."""
    response = await client.post(
        "/generate",
        json={
            "prompt": "Test database creation",
            "resolution": "m"
        },
        headers={"X-API-Key": api_key}
    )

    assert response.status_code == 200
    video_id = response.json()["video_id"]

    # Give the background task a moment to create the record
    import asyncio
    await asyncio.sleep(0.5)

    # Check that Video record exists in database
    query = 'SELECT * FROM videos WHERE video_id = :video_id'
    result = await test_db.fetch_one(query=query, values={"video_id": video_id})

    assert result is not None
    assert result["status"] == "pending" or result["status"] == "processing"
    assert result["prompt"] == "Test database creation"


@pytest.mark.asyncio
async def test_generate_unique_video_ids(client: AsyncClient, api_key: str, test_db):
    """Test that each /generate call creates a unique video ID."""
    video_ids = set()

    for _ in range(5):
        response = await client.post(
            "/generate",
            json={
                "prompt": "Test uniqueness",
                "resolution": "m"
            },
            headers={"X-API-Key": api_key}
        )

        assert response.status_code == 200
        video_id = response.json()["video_id"]
        video_ids.add(video_id)

    # All video IDs should be unique
    assert len(video_ids) == 5
