from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from database.database import SessionLocal, init_db
from models.models import Animal, Farm, Investment, User
from routers.animals import router as animals_router
from routers.farms import router as farms_router
from routers.health import router as health_router
from routers.investments import router as investments_router
from routers.users import router as users_router
from users.service import create_user, get_user_by_email, verify_password

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "live-stocks-super-secret-key-change-me")
STORAGE_PATH = Path(os.getenv("FILE_STORAGE_PATH", "./storage")).resolve()
STORAGE_PATH.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="LiveStocks Investment Platform",
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


app.include_router(health_router)
app.include_router(users_router)
app.include_router(farms_router)
app.include_router(animals_router)
app.include_router(investments_router)


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), folder: str = Form("uploads")):
    target_dir = STORAGE_PATH / folder
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = file.filename.replace("..", "").replace("\\", "/").split("/")[-1]
    if not safe_name:
        safe_name = "upload.bin"

    saved_path = target_dir / safe_name
    saved_path.write_bytes(await file.read())

    return {
        "filename": safe_name,
        "folder": folder,
        "path": str(saved_path),
        "url": f"/storage/{folder}/{safe_name}",
    }


@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
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
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"user": None, "error": None})


@app.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_user_by_email(db, email.strip())
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"user": None, "error": "Invalid email or password."},
            status_code=401,
        )

    request.session["user_id"] = user.id
    request.session["user_email"] = user.email
    request.session["user_name"] = user.full_name or user.email.split("@")[0]
    return RedirectResponse("/dashboard", status_code=303)


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
    db: Session = Depends(get_db),
):
    email = email.strip()
    if get_user_by_email(db, email):
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"user": None, "error": "User with this email already exists."},
            status_code=400,
        )

    create_user(db, email=email, password=password, role="investor", full_name=full_name.strip())
    return RedirectResponse("/login", status_code=303)


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
    user_animals = db.query(Animal).filter(Animal.owner_id == user.id).all()
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


@app.get("/animals")
def animals_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    animals = db.query(Animal).filter(Animal.is_active.is_(True), Animal.is_available.is_(True)).all()
    return templates.TemplateResponse(
        request=request,
        name="animals.html",
        context={"user": user, "animals": animals},
    )


@app.get("/support")
def support_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return templates.TemplateResponse(request=request, name="support.html", context={"user": user})


@app.get("/api")
def api_home():
    return {"message": "Welcome to the LiveStocks Investment Platform API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
