import os
from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from sqlalchemy import Column, DateTime, String, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

app = FastAPI(title="Manager Service")

DB_URL = os.getenv(
    "DB_URL",
    "mysql+pymysql://root:123456@db:3306/manager_db",
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


class ManagementTaskRow(Base):
    __tablename__ = "manager_tasks"

    id = Column(String(36), primary_key=True)
    title = Column(String(255), nullable=False)
    priority = Column(String(20), default="normal")
    status = Column(String(20), default="open")
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


class ManagementTask(BaseModel):
    id: str
    title: str
    priority: str = "normal"
    status: str = "open"


class CreateTaskRequest(BaseModel):
    title: str
    priority: str = "normal"


def row_to_task(row: ManagementTaskRow) -> ManagementTask:
    return ManagementTask(
        id=row.id,
        title=row.title,
        priority=row.priority,
        status=row.status,
    )


@app.get("/api/manager/tasks", response_model=List[ManagementTask])
def list_tasks():
    db: Session = SessionLocal()
    try:
        rows = db.query(ManagementTaskRow).order_by(ManagementTaskRow.created_at.desc()).all()
        return [row_to_task(row) for row in rows]
    finally:
        db.close()


@app.post("/api/manager/tasks", response_model=ManagementTask, status_code=201)
def create_task(payload: CreateTaskRequest):
    db: Session = SessionLocal()
    try:
        row = ManagementTaskRow(
            id=str(uuid4()),
            title=payload.title,
            priority=payload.priority,
            status="open",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row_to_task(row)
    finally:
        db.close()


@app.patch("/api/manager/tasks/{task_id}", response_model=ManagementTask)
def close_task(task_id: str, status: str):
    db: Session = SessionLocal()
    try:
        row = db.query(ManagementTaskRow).filter(ManagementTaskRow.id == task_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")

        row.status = status
        db.commit()
        db.refresh(row)
        return row_to_task(row)
    finally:
        db.close()


@app.get("/api/manager/health")
def manager_health():
    return {"service": "manager-service", "status": "ok"}
