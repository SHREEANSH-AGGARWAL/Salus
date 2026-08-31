"""
Common/shared model types used across multiple domain models.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GeoLocation(BaseModel):
    """Geographic coordinates — shared across all domain models."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
