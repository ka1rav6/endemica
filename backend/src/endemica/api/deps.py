"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from endemica.core.config import Settings, get_settings
from endemica.db.session import get_db

DbSession = Annotated[Session, Depends(get_db)]
"""A request-scoped SQLAlchemy session."""

AppSettings = Annotated[Settings, Depends(get_settings)]
"""The process-wide settings object."""
