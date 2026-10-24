from __future__ import annotations

import os
import hashlib
import hmac
import secrets
from decimal import Decimal, ROUND_HALF_UP
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from database.database import SessionLocal, init_db
from models.models import Animal, Farm, Investment, Payment, User
from routers.animals import router as animals_router
from routers.farms import router as farms_router
from routers.health import router as health_router
from routers.investments import router as investments_router
from routers.users import router as users_router
from users.service import create_user, get_user_by_email, hash_password, verify_password

load_dotenv()

configured_secret = os.getenv("SECRET_KEY", "").strip()
SECRET_KEY = configured_secret if configured_secret and "generate-a-random" not in configured_secret.lower() else secrets.token_urlsafe(48)
STORAGE_PATH = Path(os.getenv("FILE_STORAGE_PATH", "./storage")).resolve()
STORAGE_PATH.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_admin_account()
    yield


app = FastAPI(
    title="PashuNivesh | Livestock Investment Platform",
    description="Livestock investment platform for buying farm animals and tracking offspring profitability.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/storage", StaticFiles(directory=str(STORAGE_PATH)), name="storage")
templates = Jinja2Templates(directory="templates")


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def get_admin_user(request: Request, db: Session) -> Optional[User]:
    user = get_current_user(request, db)
    return user if user and user.role == "admin" else None


def ensure_admin_account() -> None:
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email or not password or email.endswith("@example.com") or "replace" in password.lower():
        return
    if len(password) < 12:
        raise RuntimeError("ADMIN_PASSWORD must be at least 12 characters long.")
    if len(password.encode("utf-8")) > 72:
        raise RuntimeError("ADMIN_PASSWORD must be no longer than 72 bytes.")

    db = SessionLocal()
    try:
        admin = get_user_by_email(db, email)
        if admin is None:
            admin = User(email=email, password_hash=hash_password(password), full_name="Administrator", role="admin")
            db.add(admin)
        else:
            admin.role = "admin"
            if not verify_password(password, admin.password_hash):
                admin.password_hash = hash_password(password)
        db.commit()
    finally:
        db.close()


def razorpay_client():
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not payments_enabled():
        return None
    try:
        import razorpay
    except ImportError:
        return None

    return razorpay.Client(auth=(key_id, key_secret))


def payments_enabled() -> bool:
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if (
        not key_id.startswith(("rzp_test_", "rzp_live_"))
        or "replace" in key_id.lower()
        or not key_secret
        or "replace" in key_secret.lower()
    ):
        return False
    try:
        import razorpay  # noqa: F401
    except ImportError:
        return False
    return True


def release_expired_payment_reservations(db: Session) -> None:
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    expired = db.query(Payment).filter(Payment.status == "pending", Payment.created_at < cutoff).all()
    for payment in expired:
        payment.status = "expired"
        animal = db.query(Animal).filter(Animal.id == payment.animal_id).first()
        if animal and animal.investor_id is None:
            animal.is_available = True
    if expired:
        db.commit()


def finalize_verified_payment(db: Session, order_id: str, payment_id: str, amount_paise: int, currency: str) -> bool:
    payment = db.query(Payment).filter(Payment.provider_order_id == order_id).first()
    if payment is None or payment.amount_paise != amount_paise or payment.currency != currency:
        return False
    if payment.status == "paid":
        return True

    animal = db.query(Animal).filter(Animal.id == payment.animal_id).first()
    if animal is None:
        return False
    if not animal.is_active:
        payment.status = "refund_required"
        payment.provider_payment_id = payment_id
        payment.failure_reason = "This animal listing was deactivated after payment. Refund review required."
        db.commit()
        return False
    existing = db.query(Investment).filter(Investment.animal_id == animal.id, Investment.is_active.is_(True)).first()
    if existing and existing.investor_id != payment.investor_id:
        payment.status = "refund_required"
        payment.provider_payment_id = payment_id
        payment.failure_reason = "Payment captured after this animal was purchased by another investor. Refund required."
        db.commit()
        return False

    now = datetime.utcnow()
    investment = existing or Investment(
        investor_id=payment.investor_id,
        animal_id=animal.id,
        amount_invested=payment.amount_paise / 100,
        ownership_percentage=100.0,
        purchased_at=now,
        is_active=True,
    )
    if existing is None:
        db.add(investment)
        db.flush()
    animal.investor_id = payment.investor_id
    animal.is_available = False
    animal.lock_until = now + timedelta(days=365)
    payment.status = "paid"
    payment.provider_payment_id = payment_id
    payment.investment_id = investment.id
    payment.paid_at = now
    payment.failure_reason = None
    db.commit()
    return True


app.include_router(health_router)
app.include_router(users_router)
app.include_router(farms_router)
app.include_router(animals_router)
app.include_router(investments_router)


@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...), folder: str = Form("uploads"), db: Session = Depends(get_db)):
    admin = get_admin_user(request, db)
    if not admin:
        return JSONResponse({"detail": "Administrator access is required"}, status_code=403)
    if folder not in {"animals", "uploads"}:
        return JSONResponse({"detail": "Invalid upload folder"}, status_code=400)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"} or (file.content_type and not file.content_type.startswith("image/")):
        return JSONResponse({"detail": "Upload a JPG, PNG, or WEBP image"}, status_code=400)
    contents = await file.read(5 * 1024 * 1024 + 1)
    if len(contents) > 5 * 1024 * 1024:
        return JSONResponse({"detail": "Images must be 5 MB or smaller"}, status_code=400)

    target_dir = STORAGE_PATH / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid4().hex}{suffix}"
    saved_path = target_dir / safe_name
    saved_path.write_bytes(contents)

    return {
        "filename": safe_name,
        "folder": folder,
        "path": f"{folder}/{safe_name}",
        "url": f"/storage/{folder}/{safe_name}",
    }


@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    release_expired_payment_reservations(db)
    featured_animals = db.query(Animal).filter(Animal.is_active.is_(True), Animal.is_available.is_(True)).limit(4).all()
    stats = {
        "animals": db.query(Animal).count(),
        "farms": db.query(Farm).count(),
        "investments": db.query(Investment).count(),
        "investors": db.query(User).count(),
    }
    user = get_current_user(request, db)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "featured_animals": featured_animals,
            "stats": stats,
            "steps": [
                ("01", "Choose an animal", "Browse listings and review the farm, animal details, and investment amount."),
                ("02", "Invest with a farm", "Your investment is associated with an animal and held through the one-year lock period."),
                ("03", "Follow its progress", "Farms record animal updates and birth events so you can follow activity over time."),
                ("04", "Share offspring value", "Recorded offspring value is allocated 50% to the investor and 50% to the farm owner."),
            ],
        },
    )


@app.get("/login")
def login_page(request: Request, registered: bool = False, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/admin" if user.role == "admin" else "/dashboard", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"user": None, "error": None, "success": "Account created successfully. You can now log in." if registered else None},
    )


@app.get("/admin/login")
def admin_login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user and user.role == "admin":
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"user": None, "error": None, "success": None, "admin_login": True},
    )


@app.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    admin: bool = False,
    db: Session = Depends(get_db),
):
    user = get_user_by_email(db, email.strip().lower())
    if not user or not verify_password(password, user.password_hash) or (admin and user.role != "admin"):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"user": None, "error": "Invalid email or password.", "admin_login": admin},
            status_code=401,
        )

    request.session["user_id"] = user.id
    request.session["user_email"] = user.email
    request.session["user_name"] = user.full_name or user.email.split("@")[0]
    return RedirectResponse("/admin" if user.role == "admin" else "/dashboard", status_code=303)


@app.get("/register")
def register_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="register.html", context={"user": None, "error": None})


@app.post("/register")
def register_submit(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("investor"),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    if role not in {"investor", "farm_owner"}:
        role = "investor"
    if get_user_by_email(db, email):
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"user": None, "error": "User with this email already exists."},
            status_code=400,
        )

    try:
        create_user(db, email=email, password=password, role=role, full_name=full_name.strip())
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"user": None, "error": str(exc)},
            status_code=400,
        )
    return RedirectResponse("/login?registered=true", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    user_farms = db.query(Farm).filter(Farm.owner_id == user.id).all()
    if user.role == "farm_owner":
        user_animals = db.query(Animal).join(Farm).filter(Farm.owner_id == user.id).all()
    else:
        user_animals = db.query(Animal).filter(Animal.investor_id == user.id).all()
    user_investments = db.query(Investment).filter(Investment.investor_id == user.id).all()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "farms": user_farms,
            "animals": user_animals,
            "investments": user_investments,
        },
    )


@app.get("/profile")
def profile_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    release_expired_payment_reservations(db)
    investments = (
        db.query(Investment)
        .filter(Investment.investor_id == user.id, Investment.is_active.is_(True))
        .order_by(Investment.purchased_at.desc())
        .all()
    )
    available_animals = (
        db.query(Animal)
        .filter(Animal.is_active.is_(True), Animal.is_available.is_(True))
        .order_by(Animal.id.desc())
        .limit(8)
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context={
            "user": user,
            "investments": investments,
            "available_animals": available_animals,
            "total_invested": sum(item.amount_invested for item in investments),
            "success": "Payment captured and the investment was recorded." if request.query_params.get("invested") else None,
            "payment_enabled": payments_enabled(),
        },
    )


async def save_animal_photo(photo: Optional[UploadFile]) -> Optional[str]:
    if photo is None or not photo.filename:
        return None
    suffix = Path(photo.filename).suffix.lower()
    allowed = {".jpg", ".jpeg", ".png", ".webp"}
    if suffix not in allowed or (photo.content_type and not photo.content_type.startswith("image/")):
        raise ValueError("Upload a JPG, PNG, or WEBP image.")
    contents = await photo.read(5 * 1024 * 1024 + 1)
    if len(contents) > 5 * 1024 * 1024:
        raise ValueError("Animal photos must be 5 MB or smaller.")
    relative_dir = Path("animals")
    target_dir = STORAGE_PATH / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{suffix}"
    (target_dir / filename).write_bytes(contents)
    return f"/storage/animals/{filename}"


@app.get("/admin")
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    admin = get_admin_user(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    release_expired_payment_reservations(db)
    animals = db.query(Animal).order_by(Animal.id.desc()).limit(100).all()
    payments = db.query(Payment).order_by(Payment.created_at.desc()).limit(100).all()
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "user": admin,
            "animals": animals,
            "payments": payments,
            "farms": db.query(Farm).order_by(Farm.name).all(),
            "users": db.query(User).order_by(User.full_name, User.email).all(),
            "animal_count": db.query(Animal).count(),
            "investor_count": db.query(User).filter(User.role != "admin").count(),
            "investment_count": db.query(Investment).count(),
            "pending_payments": db.query(Payment).filter(Payment.status == "pending").count(),
            "payment_enabled": payments_enabled(),
        },
    )


@app.post("/admin/farms")
def admin_create_farm(
    request: Request,
    name: str = Form(...),
    location: str = Form(...),
    owner_id: int = Form(...),
    db: Session = Depends(get_db),
):
    admin = get_admin_user(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    owner = db.query(User).filter(User.id == owner_id).first()
    if not owner:
        return RedirectResponse("/admin?error=Choose+a+valid+farm+owner", status_code=303)
    db.add(Farm(name=name.strip(), location=location.strip(), owner_id=owner.id))
    db.commit()
    return RedirectResponse("/admin", status_code=303)


def render_admin_animal_form(request: Request, db: Session, admin: User, animal: Optional[Animal] = None, error: Optional[str] = None, status_code: int = 200):
    return templates.TemplateResponse(
        request=request,
        name="admin_animal_form.html",
        context={"user": admin, "animal": animal, "farms": db.query(Farm).order_by(Farm.name).all(), "error": error},
        status_code=status_code,
    )


@app.get("/admin/animals/new")
def admin_new_animal_page(request: Request, db: Session = Depends(get_db)):
    admin = get_admin_user(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    return render_admin_animal_form(request, db, admin)


@app.post("/admin/animals")
async def admin_create_animal(
    request: Request,
    farm_id: int = Form(...),
    tag_number: str = Form(...),
    animal_type: str = Form(...),
    name: str = Form(...),
    breed: str = Form(""),
    gender: str = Form(...),
    age_months: int = Form(0),
    weight_kg: float = Form(0),
    market_value: float = Form(...),
    description: str = Form(""),
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    admin = get_admin_user(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    farm = db.query(Farm).filter(Farm.id == farm_id).first()
    clean_tag = tag_number.strip()
    if not farm:
        return render_admin_animal_form(request, db, admin, error="Create a farm before adding animals.", status_code=400)
    if db.query(Animal).filter(Animal.tag_number == clean_tag).first():
        return render_admin_animal_form(request, db, admin, error="That tag number is already in use.", status_code=400)
    if market_value <= 0 or age_months < 0 or weight_kg < 0 or gender.lower() not in {"female", "male"} or animal_type.lower() not in {"cow", "buffalo", "goat", "sheep", "other"}:
        return render_admin_animal_form(request, db, admin, error="Check the price, age, weight, and gender values.", status_code=400)
    try:
        image_url = await save_animal_photo(photo)
    except ValueError as exc:
        return render_admin_animal_form(request, db, admin, error=str(exc), status_code=400)
    animal = Animal(
        tag_number=clean_tag,
        animal_type=animal_type.strip().title(),
        name=name.strip(),
        breed=breed.strip() or None,
        gender=gender.strip().lower(),
        age_months=age_months,
        weight_kg=weight_kg or None,
        market_value=market_value,
        purchase_price=market_value,
        description=description.strip() or None,
        image_url=image_url,
        farm_id=farm.id,
        is_available=True,
        is_active=True,
    )
    db.add(animal)
    db.commit()
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/animals/{animal_id}/edit")
def admin_edit_animal_page(animal_id: int, request: Request, db: Session = Depends(get_db)):
    admin = get_admin_user(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    animal = db.query(Animal).filter(Animal.id == animal_id).first()
    if not animal:
        return RedirectResponse("/admin", status_code=303)
    return render_admin_animal_form(request, db, admin, animal)


@app.post("/admin/animals/{animal_id}")
async def admin_update_animal(
    animal_id: int,
    request: Request,
    farm_id: int = Form(...),
    tag_number: str = Form(...),
    animal_type: str = Form(...),
    name: str = Form(...),
    breed: str = Form(""),
    gender: str = Form(...),
    age_months: int = Form(0),
    weight_kg: float = Form(0),
    market_value: float = Form(...),
    description: str = Form(""),
    photo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    admin = get_admin_user(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    animal = db.query(Animal).filter(Animal.id == animal_id).first()
    farm = db.query(Farm).filter(Farm.id == farm_id).first()
    duplicate = db.query(Animal).filter(Animal.tag_number == tag_number.strip(), Animal.id != animal_id).first()
    if not animal:
        return RedirectResponse("/admin", status_code=303)
    if not farm or duplicate or market_value <= 0 or age_months < 0 or weight_kg < 0 or gender.lower() not in {"female", "male"} or animal_type.lower() not in {"cow", "buffalo", "goat", "sheep", "other"}:
        return render_admin_animal_form(request, db, admin, animal, "Check the farm, unique tag, price, age, weight, and gender values.", 400)
    try:
        image_url = await save_animal_photo(photo)
    except ValueError as exc:
        return render_admin_animal_form(request, db, admin, animal, str(exc), 400)
    if animal.is_available:
        animal.farm_id = farm.id
    animal.tag_number = tag_number.strip()
    animal.animal_type = animal_type.strip().title()
    animal.name = name.strip()
    animal.breed = breed.strip() or None
    animal.gender = gender.strip().lower()
    animal.age_months = age_months
    animal.weight_kg = weight_kg or None
    animal.description = description.strip() or None
    if animal.is_available:
        animal.market_value = market_value
        animal.purchase_price = market_value
    if image_url:
        animal.image_url = image_url
    db.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/animals/{animal_id}/deactivate")
def admin_deactivate_animal(animal_id: int, request: Request, db: Session = Depends(get_db)):
    admin = get_admin_user(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    animal = db.query(Animal).filter(Animal.id == animal_id).first()
    if animal:
        animal.is_active = False
        animal.is_available = False
        db.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/payments/{payment_id}/mark-refunded")
def admin_mark_payment_refunded(payment_id: int, request: Request, db: Session = Depends(get_db)):
    admin = get_admin_user(request, db)
    if not admin:
        return RedirectResponse("/admin/login", status_code=303)
    payment = db.query(Payment).filter(Payment.id == payment_id, Payment.status == "refund_required").first()
    if payment:
        payment.status = "refunded"
        payment.failure_reason = "Administrator confirmed refund was processed in Razorpay."
        db.commit()
    return RedirectResponse("/admin", status_code=303)


@app.get("/farm/animals")
def farm_animal_management(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    farms = db.query(Farm).filter(Farm.owner_id == user.id).order_by(Farm.name).all()
    listed_animals = (
        db.query(Animal)
        .join(Farm)
        .filter(Farm.owner_id == user.id)
        .order_by(Animal.id.desc())
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="farm_animals.html",
        context={"user": user, "farms": farms, "listed_animals": listed_animals, "error": None, "success": request.query_params.get("added")},
    )


@app.post("/farm/create")
def create_farm_for_owner(
    request: Request,
    name: str = Form(...),
    location: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    db.add(Farm(name=name.strip(), location=location.strip(), owner_id=user.id))
    db.commit()
    return RedirectResponse("/farm/animals", status_code=303)


@app.post("/farm/animals")
def add_farm_animal(
    request: Request,
    farm_id: int = Form(...),
    tag_number: str = Form(...),
    animal_type: str = Form(...),
    name: str = Form(...),
    breed: str = Form(""),
    gender: str = Form(...),
    age_months: int = Form(0),
    weight_kg: Optional[float] = Form(None),
    purchase_price: float = Form(0),
    market_value: float = Form(0),
    description: str = Form(""),
    image_url: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    farms = db.query(Farm).filter(Farm.owner_id == user.id).order_by(Farm.name).all()
    farm = db.query(Farm).filter(Farm.id == farm_id, Farm.owner_id == user.id).first()
    clean_tag = tag_number.strip()
    tag_exists = db.query(Animal).filter(Animal.tag_number == clean_tag).first()
    error = None
    if not farm:
        error = "Choose one of your farms before listing an animal."
    elif tag_exists:
        error = "That animal tag is already in use. Enter a unique tag number."
    elif animal_type.strip().lower() not in {"cow", "buffalo", "goat", "sheep", "other"}:
        error = "Choose a supported animal type."
    elif gender.strip().lower() not in {"female", "male"}:
        error = "Choose a valid animal gender."
    elif age_months < 0 or purchase_price < 0 or market_value < 0 or (weight_kg is not None and weight_kg < 0):
        error = "Age, weight, and prices must be zero or greater."
    elif market_value <= 0 and purchase_price <= 0:
        error = "Enter a positive investment price for this listing."

    if error:
        listed_animals = db.query(Animal).join(Farm).filter(Farm.owner_id == user.id).order_by(Animal.id.desc()).all()
        return templates.TemplateResponse(
            request=request,
            name="farm_animals.html",
            context={"user": user, "farms": farms, "listed_animals": listed_animals, "error": error, "success": None},
            status_code=400,
        )

    animal = Animal(
        tag_number=clean_tag,
        animal_type=animal_type.strip().title(),
        name=name.strip(),
        breed=breed.strip() or None,
        gender=gender.strip().lower(),
        age_months=age_months,
        weight_kg=weight_kg,
        purchase_price=purchase_price,
        market_value=market_value,
        description=description.strip() or None,
        image_url=image_url.strip() or None,
        farm_id=farm.id,
        is_available=True,
        is_active=True,
    )
    db.add(animal)
    db.commit()
    return RedirectResponse("/farm/animals?added=Animal+listed+successfully", status_code=303)


@app.post("/investments/{animal_id}")
def create_animal_payment_order(animal_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    client = razorpay_client()
    if not client:
        return RedirectResponse("/animals?payment_error=not_configured", status_code=303)
    release_expired_payment_reservations(db)
    animal = db.query(Animal).filter(Animal.id == animal_id).first()
    if not animal or not animal.is_active or not animal.is_available:
        return RedirectResponse("/animals", status_code=303)
    amount = animal.market_value or animal.purchase_price
    if amount <= 0:
        return RedirectResponse("/animals", status_code=303)
    amount_paise = int((Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) * 100)
    if amount_paise < 100:
        return RedirectResponse("/animals", status_code=303)
    receipt = f"pn-{user.id}-{animal.id}-{int(datetime.utcnow().timestamp())}"[:40]
    try:
        provider_order = client.order.create(
            data={
                "amount": amount_paise,
                "currency": "INR",
                "receipt": receipt,
                "notes": {"animal_id": str(animal.id), "investor_id": str(user.id)},
            }
        )
    except Exception:
        return RedirectResponse("/animals?payment_error=gateway", status_code=303)

    updated = (
        db.query(Animal)
        .filter(Animal.id == animal.id, Animal.is_available.is_(True), Animal.is_active.is_(True))
        .update({Animal.is_available: False}, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        return RedirectResponse("/animals", status_code=303)
    payment = Payment(
        investor_id=user.id,
        animal_id=animal.id,
        amount_paise=amount_paise,
        currency="INR",
        status="pending",
        provider_order_id=provider_order["id"],
    )
    db.add(payment)
    db.commit()
    return RedirectResponse(f"/checkout/{payment.id}", status_code=303)


@app.get("/checkout/{payment_id}")
def checkout_page(payment_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    payment = db.query(Payment).filter(Payment.id == payment_id, Payment.investor_id == user.id).first()
    if not payment or payment.status != "pending":
        return RedirectResponse("/profile", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="checkout.html",
        context={
            "user": user,
            "payment": payment,
            "animal": payment.animal,
            "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID", ""),
            "amount_rupees": payment.amount_paise / 100,
        },
    )


@app.post("/payments/verify")
async def verify_checkout_payment(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "Please sign in again to verify this payment."}, status_code=401)
    try:
        payload = await request.json()
        order_id = str(payload["razorpay_order_id"])
        payment_id = str(payload["razorpay_payment_id"])
        signature = str(payload["razorpay_signature"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "Payment verification details are incomplete."}, status_code=400)

    payment = db.query(Payment).filter(Payment.provider_order_id == order_id, Payment.investor_id == user.id).first()
    client = razorpay_client()
    secret = os.getenv("RAZORPAY_KEY_SECRET", "")
    if not payment or not client or not secret:
        return JSONResponse({"error": "Payment order could not be verified."}, status_code=400)
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        return JSONResponse({"error": "Payment signature is invalid."}, status_code=400)

    try:
        provider_payment = client.payment.fetch(payment_id)
        if (
            str(provider_payment.get("order_id")) != order_id
            or int(provider_payment.get("amount", -1)) != payment.amount_paise
            or provider_payment.get("currency") != payment.currency
        ):
            return JSONResponse({"error": "Payment amount or order does not match this animal."}, status_code=400)
        if provider_payment.get("status") == "authorized":
            client.payment.capture(payment_id, {"amount": payment.amount_paise, "currency": payment.currency})
            provider_payment = client.payment.fetch(payment_id)
    except Exception:
        return JSONResponse({"error": "We could not confirm the payment with Razorpay. Please wait a moment and retry."}, status_code=502)

    if provider_payment.get("status") != "captured":
        return JSONResponse({"error": "Payment has not been captured yet. Your animal remains reserved while we wait for confirmation."}, status_code=409)
    finalized = finalize_verified_payment(db, order_id, payment_id, payment.amount_paise, payment.currency)
    if not finalized:
        return JSONResponse({"error": "Payment was received, but the animal is no longer available. Contact support for a refund."}, status_code=409)
    return JSONResponse({"redirect_url": "/profile?invested=true"})


@app.post("/payments/{payment_id}/cancel")
def cancel_pending_payment(payment_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False}, status_code=401)
    payment = db.query(Payment).filter(Payment.id == payment_id, Payment.investor_id == user.id).first()
    if payment and payment.status == "pending":
        payment.status = "cancelled"
        animal = db.query(Animal).filter(Animal.id == payment.animal_id).first()
        if animal and animal.investor_id is None:
            animal.is_available = True
        db.commit()
    return JSONResponse({"ok": True})


@app.post("/payments/razorpay/webhook")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    signature = request.headers.get("X-Razorpay-Signature", "")
    body = await request.body()
    if not webhook_secret or not signature:
        return JSONResponse({"error": "Webhook verification is not configured."}, status_code=400)
    expected_signature = hmac.new(webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        return JSONResponse({"error": "Invalid webhook signature."}, status_code=400)
    try:
        event = await request.json()
        entity = event["payload"]["payment"]["entity"]
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "Invalid webhook payload."}, status_code=400)

    if event.get("event") == "payment.captured":
        finalize_verified_payment(
            db,
            str(entity.get("order_id", "")),
            str(entity.get("id", "")),
            int(entity.get("amount", -1)),
            str(entity.get("currency", "")),
        )
    elif event.get("event") == "payment.failed":
        payment = db.query(Payment).filter(Payment.provider_order_id == entity.get("order_id"), Payment.status == "pending").first()
        if payment:
            payment.status = "failed"
            payment.provider_payment_id = entity.get("id")
            payment.failure_reason = entity.get("error_description") or "Payment failed."
            animal = db.query(Animal).filter(Animal.id == payment.animal_id).first()
            if animal and animal.investor_id is None:
                animal.is_available = True
            db.commit()
    return JSONResponse({"ok": True})


@app.get("/animals")
def animals_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    release_expired_payment_reservations(db)
    animals = db.query(Animal).filter(Animal.is_active.is_(True), Animal.is_available.is_(True)).all()
    return templates.TemplateResponse(
        request=request,
        name="animals.html",
        context={
            "user": user,
            "animals": animals,
            "payment_enabled": payments_enabled(),
            "payment_error": request.query_params.get("payment_error"),
        },
    )


@app.get("/support")
def support_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return templates.TemplateResponse(request=request, name="support.html", context={"user": user})


@app.get("/api")
def api_home():
    return {"message": "Welcome to the PashuNivesh Livestock Investment Platform API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
