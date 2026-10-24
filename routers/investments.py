from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database.database import SessionLocal
from exceptions.custom import BusinessRuleError
from models.models import Animal, Investment
from schemas.investment import InvestmentCreate, InvestmentRead

router = APIRouter(prefix="/api/investments", tags=["investments"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/", response_model=list[InvestmentRead])
def list_investments(db: Session = Depends(get_db)):
    return db.query(Investment).all()


@router.get("/{investment_id}", response_model=InvestmentRead)
def get_investment(investment_id: int, db: Session = Depends(get_db)):
    investment = db.query(Investment).filter(Investment.id == investment_id).first()
    if not investment:
        raise HTTPException(status_code=404, detail="Investment not found")
    return investment


@router.post("/", response_model=InvestmentRead, status_code=status.HTTP_201_CREATED)
def create_investment(payload: InvestmentCreate, db: Session = Depends(get_db)):
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Investments must be created through the authenticated payment checkout.",
    )


@router.post("/{investment_id}/sell")
def sell_investment(investment_id: int, db: Session = Depends(get_db)):
    investment = db.query(Investment).filter(Investment.id == investment_id).first()
    if not investment:
        raise HTTPException(status_code=404, detail="Investment not found")

    animal = db.query(Animal).filter(Animal.id == investment.animal_id).first()
    if not animal:
        raise HTTPException(status_code=404, detail="Animal not found")

    if not animal.births:
        raise HTTPException(status_code=400, detail="Investor cannot sell until the animal produces offspring")

    if animal.is_locked:
        raise HTTPException(status_code=400, detail="Investor cannot sell until the 1-year lock period ends")

    investment.can_sell = True
    db.commit()
    return {"message": "Investment marked for sale", "can_sell": True}
