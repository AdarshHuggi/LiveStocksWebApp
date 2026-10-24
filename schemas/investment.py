from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class InvestmentCreate(BaseModel):
    investor_id: int
    animal_id: int
    amount_invested: float = Field(..., gt=0)
    ownership_percentage: float = Field(default=100.0, ge=0, le=100)


class InvestmentRead(InvestmentCreate):
    id: int
    purchased_at: datetime
    can_sell: bool = False
    is_active: bool = True

    class Config:
        from_attributes = True


class InvestmentTransfer(BaseModel):
    investor_id: int
    animal_id: int
    amount: float
