import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import Column, Integer, String, Text, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

app = FastAPI(title="Catalog Service")

DB_URL = os.getenv(
    "DB_URL",
    "mysql+pymysql://root:123456@db:3306/catalog_db",
)


def ensure_database_exists(db_url: str):
    url = make_url(db_url)
    db_name = url.database
    if not db_name:
        return

    server_engine = create_engine(url.set(database="mysql"), pool_pre_ping=True)
    with server_engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
    server_engine.dispose()


ensure_database_exists(DB_URL)

engine = create_engine(DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class CatalogItemRow(Base):
    __tablename__ = "catalog_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)


Base.metadata.create_all(bind=engine)


class CatalogItem(BaseModel):
    id: int
    name: str
    description: Optional[str] = None


class CatalogItemCreate(BaseModel):
    name: str
    description: Optional[str] = None


def row_to_item(row: CatalogItemRow) -> CatalogItem:
    return CatalogItem(id=row.id, name=row.name, description=row.description)


def seed_default_data_if_empty():
    db: Session = SessionLocal()
    try:
        count = db.query(CatalogItemRow).count()
        if count == 0:
            db.add_all(
                [
                    CatalogItemRow(name="Fiction", description="Fiction books"),
                    CatalogItemRow(name="Technology", description="Programming and technology books"),
                ]
            )
            db.commit()
    finally:
        db.close()


seed_default_data_if_empty()


@app.get("/api/catalog/items", response_model=List[CatalogItem])
def list_catalog_items():
    db: Session = SessionLocal()
    try:
        rows = db.query(CatalogItemRow).order_by(CatalogItemRow.id.asc()).all()
        return [row_to_item(row) for row in rows]
    finally:
        db.close()


@app.post("/api/catalog/items", response_model=CatalogItem, status_code=201)
def add_catalog_item(payload: CatalogItemCreate):
    db: Session = SessionLocal()
    try:
        row = CatalogItemRow(name=payload.name, description=payload.description)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row_to_item(row)
    finally:
        db.close()


@app.get("/api/catalog/items/{item_id}", response_model=CatalogItem)
def get_catalog_item(item_id: int):
    db: Session = SessionLocal()
    try:
        row = db.query(CatalogItemRow).filter(CatalogItemRow.id == item_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Catalog item not found")
        return row_to_item(row)
    finally:
        db.close()


@app.get("/api/catalog/health")
def catalog_health():
    return {"service": "catalog-service", "status": "ok"}
