"""
Tests for database operations.

This module tests the database layer including:
- Database connection
- Video record CRUD operations
- VideoStatus record creation
- Status updates
"""

import pytest
from datetime import datetime
from db import (
    create_video_record,
    update_video_status,
    get_video_status
)


@pytest.mark.asyncio
@pytest.mark.database
async def test_database_connection(test_db):
    """Test that database connection works."""
    # Try a simple query
    query = "SELECT 1 as test"
    result = await test_db.fetch_one(query=query)
    assert result["test"] == 1


@pytest.mark.asyncio
@pytest.mark.database
async def test_create_video_record(test_db):
    """Test creating a new Video record."""
    video_id = "test-video-123"
    prompt = "Test prompt"

    await create_video_record(video_id, prompt=prompt)

    # Verify record was created
    query = 'SELECT * FROM videos WHERE video_id = :video_id'
    result = await test_db.fetch_one(query=query, values={"video_id": video_id})

    assert result is not None
    assert result["video_id"] == video_id
    assert result["prompt"] == prompt
    assert result["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.database
async def test_create_video_record_with_user_id(test_db):
    """Test creating a Video record with user ID."""
    video_id = "test-video-456"

    # Create a test user first (to satisfy foreign key constraint)
    user_id = "test-user-123"
    create_user_query = """
        INSERT INTO users (id, email, password, created_at, updated_at)
        VALUES (:id, :email, :password, NOW(), NOW())
        ON CONFLICT (id) DO NOTHING
    """
    await test_db.execute(
        query=create_user_query,
        values={
            "id": user_id,
            "email": "test@example.com",
            "password": "hashed_password"
        }
    )

    prompt = "User's test prompt"
    await create_video_record(video_id, user_id=user_id, prompt=prompt)

    # Verify record
    query = 'SELECT * FROM videos WHERE video_id = :video_id'
    result = await test_db.fetch_one(query=query, values={"video_id": video_id})

    assert result is not None
    assert result["user_id"] == user_id


@pytest.mark.asyncio
@pytest.mark.database
async def test_update_video_status_processing(test_db):
    """Test updating video status to processing."""
    video_id = "test-video-789"

    # Create video first
    await create_video_record(video_id, prompt="Test")

    # Update to processing
    await update_video_status(
        video_id=video_id,
        status="processing",
        step=1,
        step_message="Generating script"
    )

    # Verify update
    query = 'SELECT * FROM videos WHERE video_id = :video_id'
    result = await test_db.fetch_one(query=query, values={"video_id": video_id})

    assert result["status"] == "processing"

    # Verify VideoStatus record was created
    status_query = 'SELECT * FROM video_statuses WHERE video_id = :video_id AND step = :step'
    status_result = await test_db.fetch_one(
        query=status_query,
        values={"video_id": video_id, "step": 1}
    )

    assert status_result is not None
    assert status_result["message"] == "Generating script"


@pytest.mark.asyncio
@pytest.mark.database
async def test_update_video_status_completed(test_db):
    """Test updating video status to completed with file path."""
    video_id = "test-video-completed"

    # Create video first
    await create_video_record(video_id, prompt="Test")

    # Update to completed
    await update_video_status(
        video_id=video_id,
        status="completed",
        step=4,
        step_message="Generation completed",
        video_url="/api/videos/file/test-video-completed",
        duration=30.5
    )

    # Verify update
    query = 'SELECT * FROM videos WHERE video_id = :video_id'
    result = await test_db.fetch_one(query=query, values={"video_id": video_id})

    assert result["status"] == "completed"
    assert result["video_url"] == "/api/videos/file/test-video-completed"
    assert result["duration"] == 30.5


@pytest.mark.asyncio
@pytest.mark.database
async def test_update_video_status_failed(test_db):
    """Test updating video status to failed."""
    video_id = "test-video-failed"

    # Create video first
    await create_video_record(video_id, prompt="Test")

    # Update to failed
    await update_video_status(
        video_id=video_id,
        status="failed",
        step=2,
        step_message="Generation failed: Test error",
        error="Test error"
    )

    # Verify update
    query = 'SELECT * FROM videos WHERE video_id = :video_id'
    result = await test_db.fetch_one(query=query, values={"video_id": video_id})

    assert result["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.database
async def test_get_video_status(test_db):
    """Test retrieving video status from database."""
    video_id = "test-video-get-status"

    # Create video and add status
    await create_video_record(video_id, prompt="Test")
    await update_video_status(
        video_id=video_id,
        status="processing",
        step=2,
        step_message="Rendering animation",
        duration=15.0
    )

    # Get status
    status = await get_video_status(video_id)

    assert status is not None
    assert status["video_id"] == video_id
    assert status["status"] == "processing"
    assert status["step"] == 2
    assert status["message"] == "Rendering animation"
    assert status["duration"] == 15.0


@pytest.mark.asyncio
@pytest.mark.database
async def test_get_video_status_not_found(test_db):
    """Test getting status for non-existent video."""
    status = await get_video_status("non-existent-video")
    assert status is None


@pytest.mark.asyncio
@pytest.mark.database
async def test_video_status_unique_constraint(test_db):
    """Test that VideoStatus has unique constraint on (videoId, step)."""
    video_id = "test-unique-constraint"

    # Create video
    await create_video_record(video_id, prompt="Test")

    # Create first status for step 1
    await update_video_status(
        video_id=video_id,
        status="processing",
        step=1,
        step_message="First message"
    )

    # Try to create another status for step 1 (should update, not duplicate)
    await update_video_status(
        video_id=video_id,
        status="processing",
        step=1,
        step_message="Second message"
    )

    # Verify only one record exists for step 1
    query = 'SELECT COUNT(*) as count FROM video_statuses WHERE video_id = :video_id AND step = 1'
    result = await test_db.fetch_one(query=query, values={"video_id": video_id})

    assert result["count"] == 1

    # Verify the message was updated
    status_query = 'SELECT * FROM video_statuses WHERE video_id = :video_id AND step = 1'
    status_result = await test_db.fetch_one(
        query=status_query,
        values={"video_id": video_id}
    )

    assert status_result["message"] == "Second message"


@pytest.mark.asyncio
@pytest.mark.database
async def test_multiple_status_steps(test_db):
    """Test creating multiple status steps for the same video."""
    video_id = "test-multiple-steps"

    # Create video
    await create_video_record(video_id, prompt="Test")

    # Create status for steps 0-4
    for step in range(5):
        await update_video_status(
            video_id=video_id,
            status="processing",
            step=step,
            step_message=f"Step {step}"
        )

    # Verify all steps exist
    query = 'SELECT COUNT(*) as count FROM video_statuses WHERE video_id = :video_id'
    result = await test_db.fetch_one(query=query, values={"video_id": video_id})

    assert result["count"] == 5
