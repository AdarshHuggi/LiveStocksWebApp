from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FarmCreate(BaseModel):
    name: str
    location: str
    owner_id: int


class FarmRead(FarmCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
