"""Response models for the Library."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class LibraryItemOut(BaseModel):
    id: uuid.UUID
    bot_id: uuid.UUID | None
    run_id: uuid.UUID | None
    kind: Literal["file", "page", "result"]
    category: Literal["document", "image", "pdf", "other"]
    title: str
    path: str | None
    mime: str | None
    size_bytes: int | None
    created_at: datetime
    updated_at: datetime


class LibraryItemDetail(LibraryItemOut):
    # Works for a few minutes without sign-in: for the preview and for saving the file.
    download_url: str
