import json
import os
from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

app = FastAPI(title="Recommender AI Service")

DB_URL = os.getenv(
    "DB_URL",
    "mysql+pymysql://root:123456@host.docker.internal:3306/recommender_db",
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


class RecommendationEventRow(Base):
    __tablename__ = "recommendation_events"

    id = Column(String(36), primary_key=True)
    customer_id = Column(Integer, nullable=False, index=True)
    viewed_book_ids = Column(Text, nullable=False)
    recommendations = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserPreferenceRow(Base):
    __tablename__ = "recommender_user_preferences"

    customer_id = Column(Integer, primary_key=True)
    viewed_book_ids = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


class RecommendRequest(BaseModel):
    customer_id: int
    viewed_book_ids: List[int] = []


class Recommendation(BaseModel):
    book_id: int
    score: float
    reason: str


BOOK_POOL = [
    {"book_id": 1, "tags": {"fiction", "classic"}},
    {"book_id": 2, "tags": {"tech", "python"}},
    {"book_id": 3, "tags": {"business", "startup"}},
    {"book_id": 4, "tags": {"fiction", "mystery"}},
    {"book_id": 5, "tags": {"tech", "ai"}},
    {"book_id": 6, "tags": {"self-help", "growth"}},
]


@app.post("/api/recommendations", response_model=List[Recommendation])
def get_recommendations(payload: RecommendRequest):
    seen = set(payload.viewed_book_ids)
    recommendations: List[Recommendation] = []

    for book in BOOK_POOL:
        if book["book_id"] in seen:
            continue

        overlap_bonus = 0.0
        if seen:
            overlap_bonus = 0.1

        score = round(0.7 + overlap_bonus - (book["book_id"] * 0.01), 3)
        recommendations.append(
            Recommendation(
                book_id=book["book_id"],
                score=max(score, 0.1),
                reason="Heuristic ranking based on viewed books"
            )
        )

    recommendations.sort(key=lambda item: item.score, reverse=True)
    final_recommendations = recommendations[:5]

    db: Session = SessionLocal()
    try:
        profile = db.query(UserPreferenceRow).filter(UserPreferenceRow.customer_id == payload.customer_id).first()
        viewed_json = json.dumps(payload.viewed_book_ids)
        now = datetime.utcnow()
        if profile:
            profile.viewed_book_ids = viewed_json
            profile.updated_at = now
        else:
            db.add(
                UserPreferenceRow(
                    customer_id=payload.customer_id,
                    viewed_book_ids=viewed_json,
                    updated_at=now,
                )
            )

        db.add(
            RecommendationEventRow(
                id=str(uuid4()),
                customer_id=payload.customer_id,
                viewed_book_ids=viewed_json,
                recommendations=json.dumps([rec.model_dump() for rec in final_recommendations]),
                created_at=now,
            )
        )
        db.commit()
    finally:
        db.close()

    return final_recommendations


@app.get("/api/recommendations/history")
def recommendation_history(customer_id: int | None = None, limit: int = 20):
    db: Session = SessionLocal()
    try:
        query = db.query(RecommendationEventRow)
        if customer_id is not None:
            query = query.filter(RecommendationEventRow.customer_id == customer_id)

        rows = query.order_by(RecommendationEventRow.created_at.desc()).limit(max(1, min(limit, 100))).all()

        return [
            {
                "id": row.id,
                "customer_id": row.customer_id,
                "viewed_book_ids": json.loads(row.viewed_book_ids or "[]"),
                "recommendations": json.loads(row.recommendations or "[]"),
                "created_at": row.created_at,
            }
            for row in rows
        ]
    finally:
        db.close()


@app.get("/api/recommendations/health")
def recommender_health():
    return {"service": "recommender-ai-service", "status": "ok"}
