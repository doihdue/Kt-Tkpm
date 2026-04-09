from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DB_URL


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


class KnowledgeDocument(Base):
    __tablename__ = "kb_documents"

    id = Column(String(64), primary_key=True)
    source_type = Column(String(32), nullable=False, index=True)
    source_id = Column(String(64), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, index=True)


class KnowledgeChunk(Base):
    __tablename__ = "kb_chunks"

    id = Column(String(64), primary_key=True)
    document_id = Column(String(64), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False, default=0)
    norm = Column(Float, nullable=False, default=1.0)
    vector_json = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, index=True)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String(64), primary_key=True)
    customer_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, index=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String(64), primary_key=True)
    session_id = Column(String(64), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    citations_json = Column(Text, nullable=True)
    context_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ChatFeedback(Base):
    __tablename__ = "chat_feedback"

    id = Column(String(64), primary_key=True)
    message_id = Column(String(64), nullable=False, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    score = Column(Integer, nullable=False, default=0)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


Base.metadata.create_all(bind=engine)


def ensure_chat_schema_runtime() -> None:
    with engine.begin() as conn:
        exists = conn.execute(
            text("SHOW COLUMNS FROM chat_messages LIKE 'context_json'")
        ).first()
        if not exists:
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN context_json TEXT NULL"))


ensure_chat_schema_runtime()
