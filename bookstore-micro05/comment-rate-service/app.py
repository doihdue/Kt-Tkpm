import os
from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

app = FastAPI(title="Comment Rate Service")

DB_URL = os.getenv(
    "DB_URL",
    "mysql+pymysql://root:123456@db:3306/comment_rate_db",
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


class CommentRateRow(Base):
    __tablename__ = "comment_rates"

    id = Column(String(36), primary_key=True)
    book_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False, index=True)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


class CommentRateCreate(BaseModel):
    book_id: int
    customer_id: int
    rating: int = Field(ge=1, le=5)
    comment: str


class CommentRate(CommentRateCreate):
    id: str
    created_at: datetime | None = None


def row_to_comment_rate(row: CommentRateRow) -> CommentRate:
    return CommentRate(
        id=row.id,
        book_id=row.book_id,
        customer_id=row.customer_id,
        rating=row.rating,
        comment=row.comment,
        created_at=row.created_at,
    )


@app.get("/api/comment-rates", response_model=List[CommentRate])
def list_comment_rates(book_id: int | None = None):
    db: Session = SessionLocal()
    try:
        query = db.query(CommentRateRow)
        if book_id is not None:
            query = query.filter(CommentRateRow.book_id == book_id)
        rows = query.order_by(CommentRateRow.created_at.desc()).all()
        return [row_to_comment_rate(row) for row in rows]
    finally:
        db.close()


@app.post("/api/comment-rates", response_model=CommentRate, status_code=201)
def create_comment_rate(payload: CommentRateCreate):
    db: Session = SessionLocal()
    try:
        row = CommentRateRow(id=str(uuid4()), **payload.model_dump())
        db.add(row)
        db.commit()
        db.refresh(row)
        return row_to_comment_rate(row)
    finally:
        db.close()


@app.delete("/api/comment-rates/{review_id}", status_code=204)
def delete_comment_rate(review_id: str):
    db: Session = SessionLocal()
    try:
        row = db.query(CommentRateRow).filter(CommentRateRow.id == review_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Review not found")
        db.delete(row)
        db.commit()
        return None
    finally:
        db.close()


@app.get("/api/comment-rates/summary/{book_id}")
def summary_by_book(book_id: int):
    db: Session = SessionLocal()
    try:
        book_records = db.query(CommentRateRow).filter(CommentRateRow.book_id == book_id).all()
    finally:
        db.close()

    if not book_records:
        return {"book_id": book_id, "count": 0, "avg_rating": 0}

    avg_rating = sum(record.rating for record in book_records) / len(book_records)
    return {"book_id": book_id, "count": len(book_records), "avg_rating": round(avg_rating, 2)}


@app.get("/api/comment-rates/health")
def comment_rate_health():
    return {"service": "comment-rate-service", "status": "ok"}
