from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database.database import SessionLocal
from models.models import Farm, User
from schemas.farm import FarmCreate, FarmRead

router = APIRouter(prefix="/api/farms", tags=["farms"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_admin(request: Request, db: Session) -> User:
    user_id = request.session.get("user_id")
    user = db.query(User).filter(User.id == user_id).first() if user_id else None
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required")
    return user


@router.get("/", response_model=list[FarmRead])
def list_farms(db: Session = Depends(get_db)):
    return db.query(Farm).all()


@router.get("/{farm_id}", response_model=FarmRead)
def get_farm(farm_id: int, db: Session = Depends(get_db)):
    farm = db.query(Farm).filter(Farm.id == farm_id).first()
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")
    return farm


@router.post("/", response_model=FarmRead, status_code=status.HTTP_201_CREATED)
def create_farm(payload: FarmCreate, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    owner = db.query(User).filter(User.id == payload.owner_id).first()
    if not owner:
        raise HTTPException(status_code=404, detail="Owner not found")

    farm = Farm(name=payload.name, location=payload.location, owner_id=payload.owner_id)
    db.add(farm)
    db.commit()
    db.refresh(farm)
    return farm
