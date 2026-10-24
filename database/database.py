from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./livestock.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    # Import all models here to ensure tables are created using the same model module.
    from models.models import Animal, BirthHistory, Farm, Investment, Payment, User

    Base.metadata.create_all(bind=engine)

    # create_all doesn't add columns to an existing SQLite database.
    if engine.dialect.name == "sqlite" and "animals" in inspect(engine).get_table_names():
        existing_columns = {column["name"] for column in inspect(engine).get_columns("animals")}
        animal_columns = {
            "breed": "VARCHAR(120)",
            "weight_kg": "FLOAT",
            "description": "TEXT",
            "image_url": "VARCHAR(500)",
            "investor_id": "INTEGER REFERENCES users(id)",
        }
        with engine.begin() as connection:
            for name, column_type in animal_columns.items():
                if name not in existing_columns:
                    connection.execute(text(f"ALTER TABLE animals ADD COLUMN {name} {column_type}"))
            if "investor_id" not in existing_columns and "owner_id" in existing_columns:
                connection.execute(text("UPDATE animals SET investor_id = owner_id WHERE investor_id IS NULL"))
