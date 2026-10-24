from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AnimalBase(BaseModel):
    tag_number: str
    animal_type: str = Field(..., description="Goat, Sheep, Cow, Buffalo")
    name: str
    gender: str
    age_months: int = 0
    purchase_price: float = 0.0
    market_value: float = 0.0
    farm_id: int
    owner_id: Optional[int] = None


class AnimalCreate(AnimalBase):
    pass


class AnimalUpdate(BaseModel):
    name: Optional[str] = None
    age_months: Optional[int] = None
    market_value: Optional[float] = None
    is_available: Optional[bool] = None
    is_active: Optional[bool] = None


class AnimalRead(AnimalBase):
    id: int
    purchased_at: datetime
    lock_until: Optional[datetime] = None
    is_available: bool
    is_active: bool

    class Config:
        from_attributes = True


class BirthRecordCreate(BaseModel):
    animal_id: int
    offspring_tag_number: str
    offspring_type: str
    offspring_gender: str
    offspring_value: float
    notes: Optional[str] = None


class BirthRecordRead(BirthRecordCreate):
    id: int
    birth_date: datetime
    investor_share: float = 50.0
    farm_owner_share: float = 50.0

    class Config:
        from_attributes = True
