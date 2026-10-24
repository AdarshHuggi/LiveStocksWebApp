from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="investor")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    farms: Mapped[list["Farm"]] = relationship(back_populates="owner")
    investments: Mapped[list["Investment"]] = relationship(back_populates="investor")


class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped[User] = relationship(back_populates="farms")
    animals: Mapped[list["Animal"]] = relationship(back_populates="farm")


class Animal(Base):
    __tablename__ = "animals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tag_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    animal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    breed: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    gender: Mapped[str] = mapped_column(String(20), nullable=False)
    age_months: Mapped[int] = mapped_column(Integer, default=0)
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    purchase_price: Mapped[float] = mapped_column(Float, default=0.0)
    market_value: Mapped[float] = mapped_column(Float, default=0.0)
    purchased_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    lock_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), nullable=False)
    investor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    farm: Mapped[Farm] = relationship(back_populates="animals")
    investor: Mapped[Optional[User]] = relationship()
    investments: Mapped[list["Investment"]] = relationship(back_populates="animal")
    births: Mapped[list["BirthHistory"]] = relationship(back_populates="animal")

    @property
    def is_locked(self) -> bool:
        if self.lock_until is None:
            return False
        return datetime.utcnow() < self.lock_until

    @property
    def farm_owner_name(self) -> Optional[str]:
        if not self.farm or not self.farm.owner:
            return None
        return self.farm.owner.full_name or self.farm.owner.email


class Investment(Base):
    __tablename__ = "investments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    investor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    animal_id: Mapped[int] = mapped_column(ForeignKey("animals.id"), nullable=False)
    amount_invested: Mapped[float] = mapped_column(Float, nullable=False)
    ownership_percentage: Mapped[float] = mapped_column(Float, default=100.0)
    purchased_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    can_sell: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    investor: Mapped[User] = relationship(back_populates="investments")
    animal: Mapped[Animal] = relationship(back_populates="investments")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    investor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    animal_id: Mapped[int] = mapped_column(ForeignKey("animals.id"), nullable=False, index=True)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    provider_order_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True)
    investment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("investments.id"), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    investor: Mapped[User] = relationship()
    animal: Mapped[Animal] = relationship()
    investment: Mapped[Optional[Investment]] = relationship()


class BirthHistory(Base):
    __tablename__ = "birth_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    animal_id: Mapped[int] = mapped_column(ForeignKey("animals.id"), nullable=False)
    offspring_tag_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    offspring_type: Mapped[str] = mapped_column(String(50), nullable=False)
    offspring_gender: Mapped[str] = mapped_column(String(20), nullable=False)
    offspring_value: Mapped[float] = mapped_column(Float, nullable=False)
    birth_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    investor_share: Mapped[float] = mapped_column(Float, default=50.0)
    farm_owner_share: Mapped[float] = mapped_column(Float, default=50.0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    animal: Mapped[Animal] = relationship(back_populates="births")


class InvestmentReturn(Base):
    __tablename__ = "investment_returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    investment_id: Mapped[int] = mapped_column(ForeignKey("investments.id"), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    period_end: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    profit_amount: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
