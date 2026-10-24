from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database.database import SessionLocal
from exceptions.custom import BusinessRuleError
from models.models import Animal, BirthHistory, Farm, Investment, User
from schemas.animal import AnimalCreate, AnimalRead, AnimalUpdate, BirthRecordCreate, BirthRecordRead

router = APIRouter(prefix="/api/animals", tags=["animals"])


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


@router.get("/", response_model=list[AnimalRead])
def list_animals(db: Session = Depends(get_db)):
    return db.query(Animal).all()


@router.get("/{animal_id}", response_model=AnimalRead)
def get_animal(animal_id: int, db: Session = Depends(get_db)):
    animal = db.query(Animal).filter(Animal.id == animal_id).first()
    if not animal:
        raise HTTPException(status_code=404, detail="Animal not found")
    return animal


@router.post("/", response_model=AnimalRead, status_code=status.HTTP_201_CREATED)
def create_animal(payload: AnimalCreate, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    farm = db.query(Farm).filter(Farm.id == payload.farm_id).first()
    if not farm:
        raise HTTPException(status_code=404, detail="Farm not found")

    animal = Animal(
        tag_number=payload.tag_number,
        animal_type=payload.animal_type,
        name=payload.name,
        breed=payload.breed,
        gender=payload.gender,
        age_months=payload.age_months,
        weight_kg=payload.weight_kg,
        description=payload.description,
        image_url=payload.image_url,
        purchase_price=payload.purchase_price,
        market_value=payload.market_value,
        farm_id=payload.farm_id,
    )
    db.add(animal)
    db.commit()
    db.refresh(animal)
    return animal


@router.patch("/{animal_id}", response_model=AnimalRead)
def update_animal(animal_id: int, payload: AnimalUpdate, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    animal = db.query(Animal).filter(Animal.id == animal_id).first()
    if not animal:
        raise HTTPException(status_code=404, detail="Animal not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(animal, field, value)

    db.commit()
    db.refresh(animal)
    return animal


@router.post("/{animal_id}/births", response_model=BirthRecordRead)
def record_birth(animal_id: int, payload: BirthRecordCreate, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    animal = db.query(Animal).filter(Animal.id == animal_id).first()
    if not animal:
        raise HTTPException(status_code=404, detail="Animal not found")

    if animal.gender.lower() not in {"female", "f"}:
        raise HTTPException(status_code=400, detail="Only female animals can produce offspring")

    existing_birth = db.query(BirthHistory).filter(BirthHistory.offspring_tag_number == payload.offspring_tag_number).first()
    if existing_birth:
        raise HTTPException(status_code=400, detail="Birth record with this tag already exists")

    birth = BirthHistory(
        animal_id=animal.id,
        offspring_tag_number=payload.offspring_tag_number,
        offspring_type=payload.offspring_type,
        offspring_gender=payload.offspring_gender,
        offspring_value=payload.offspring_value,
        notes=payload.notes,
        investor_share=50.0,
        farm_owner_share=50.0,
    )
    db.add(birth)

    animal.is_available = False
    animal.lock_until = datetime.utcnow() + timedelta(days=365)

    db.commit()
    db.refresh(birth)
    return birth


@router.get("/{animal_id}/births", response_model=list[BirthRecordRead])
def list_births(animal_id: int, db: Session = Depends(get_db)):
    animal = db.query(Animal).filter(Animal.id == animal_id).first()
    if not animal:
        raise HTTPException(status_code=404, detail="Animal not found")
    return db.query(BirthHistory).filter(BirthHistory.animal_id == animal_id).all()


@router.post("/{animal_id}/disable")
def deactivate_animal(animal_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    animal = db.query(Animal).filter(Animal.id == animal_id).first()
    if not animal:
        raise HTTPException(status_code=404, detail="Animal not found")
    animal.is_active = False
    db.commit()
    return {"message": "Animal deactivated"}
