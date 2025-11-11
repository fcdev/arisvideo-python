"""
API Key Authentication Middleware for video generation service
"""
import os
from fastapi import HTTPException, Header
from typing import Optional


def verify_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    """
    Verify that the API key in the request header matches the configured key.

    Args:
        x_api_key: API key from X-API-Key header

    Raises:
        HTTPException: 401 if API key is missing or invalid
    """
    expected_api_key = os.getenv("API_KEY")

    if not expected_api_key:
        raise HTTPException(
            status_code=500,
            detail="API_KEY not configured on server"
        )

    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing X-API-Key header"
        )

    if x_api_key != expected_api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
