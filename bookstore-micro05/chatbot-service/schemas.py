from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class IngestResponse(BaseModel):
    ok: bool
    documents_upserted: int
    chunks_upserted: int


class SearchResult(BaseModel):
    chunk_id: str
    score: float
    document_id: str
    title: str
    snippet: str
    detail_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=2)
    customer_id: Optional[int] = None
    session_id: Optional[str] = None
    top_k: int = 5


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    citations: List[SearchResult]


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations: List[SearchResult]
    created_at: datetime


class FeedbackRequest(BaseModel):
    message_id: str
    customer_id: Optional[int] = None
    score: int = Field(ge=-1, le=1)
    comment: Optional[str] = None
