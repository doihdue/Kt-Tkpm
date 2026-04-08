import json
import math
import os
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

app = FastAPI(title="Chatbot Service")

DB_URL = os.getenv("DB_URL", "mysql+pymysql://root:123456@db:3306/chatbot_db")
BOOK_SERVICE_URL = os.getenv("BOOK_SERVICE_URL", "http://book-service:8000")
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8000")
BOOK_DETAIL_BASE_URL = os.getenv("BOOK_DETAIL_BASE_URL", "")
MAX_CONTEXT_CHUNKS = int(os.getenv("MAX_CONTEXT_CHUNKS", "5"))
LLM_API_BASE_URL = os.getenv("LLM_API_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "20"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "220"))


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
    # Keep schema forward-compatible in environments without migrations.
    with engine.begin() as conn:
        exists = conn.execute(
            text("SHOW COLUMNS FROM chat_messages LIKE 'context_json'")
        ).first()
        if not exists:
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN context_json TEXT NULL"))


ensure_chat_schema_runtime()


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


def tokenize(text_value: str) -> List[str]:
    raw = (text_value or "").lower()
    normalized = normalize_text(raw)
    raw_tokens = re.findall(r"[a-z0-9a-zA-Z\u00C0-\u024F\u1E00-\u1EFF]+", raw)
    normalized_tokens = re.findall(r"[a-z0-9]+", normalized)
    return raw_tokens + normalized_tokens


def normalize_text(text_value: str) -> str:
    if not text_value:
        return ""
    lowered = text_value.lower().strip()
    normalized = unicodedata.normalize("NFD", lowered)
    no_marks = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return no_marks.replace("đ", "d")


STOPWORDS: Set[str] = {
    "sach",
    "goi",
    "y",
    "toi",
    "muon",
    "tim",
    "cho",
    "xin",
    "hay",
    "va",
    "la",
    "co",
    "the",
    "duoc",
    "gia",
    "book",
    "books",
    "sachv",
    "nhung",
    "cac",
    "nhieu",
    "tac",
    "gia",
    "cua",
}


BOOK_INTENT_KEYWORDS: Set[str] = {
    "sach",
    "book",
    "books",
    "tac gia",
    "the loai",
    "gia",
    "mua",
    "goi y",
    "de xuat",
    "doc",
    "nha xuat ban",
    "ton kho",
    "noi dung",
}


CATEGORY_KEYWORDS: Dict[str, Set[str]] = {
    "Văn học": {"van hoc", "tieu thuyet", "truyen"},
    "Kinh doanh": {"kinh doanh", "quan tri", "marketing", "khoi nghiep"},
    "Công nghệ": {"cong nghe", "lap trinh", "python", "ai", "du lieu", "microservice", "docker"},
    "Khoa học": {"khoa hoc", "vat ly", "sinh hoc", "vu tru", "logic"},
    "Tâm lý - Kỹ năng": {"tam ly", "ky nang", "giao tiep", "dam phan", "thoi quen"},
    "Lịch sử": {"lich su", "van minh", "chien tranh"},
    "Thiếu nhi": {"thieu nhi", "tre em", "co tich"},
}


def _parse_money_number(raw_value: str) -> Optional[float]:
    if not raw_value:
        return None
    normalized = raw_value.strip().lower().replace(" ", "")
    normalized = normalized.replace("đ", "").replace("vnd", "")
    scale = 1.0
    if normalized.endswith("trieu"):
        scale = 1_000_000.0
        normalized = normalized[:-5]
    elif normalized.endswith("tr"):
        scale = 1_000_000.0
        normalized = normalized[:-2]
    elif normalized.endswith("nghin"):
        scale = 1_000.0
        normalized = normalized[:-5]
    elif normalized.endswith("ngan"):
        scale = 1_000.0
        normalized = normalized[:-4]
    elif normalized.endswith("k"):
        scale = 1_000.0
        normalized = normalized[:-1]

    cleaned = normalized.replace(",", ".")
    if cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")

    try:
        return float(cleaned) * scale
    except ValueError:
        return None


def _extract_price_constraints(message: str) -> Tuple[Optional[float], Optional[float]]:
    text_norm = normalize_text(message)

    max_price: Optional[float] = None
    min_price: Optional[float] = None

    unit = r"(?:k|tr|trieu|nghin|ngan|vnd|đ)?"
    max_patterns = [
        rf"(?:duoi|nho hon|khong qua|toi da|max)\s*(\d+[\d\.,]*\s*{unit})",
        rf"<\s*(\d+[\d\.,]*\s*{unit})",
    ]
    min_patterns = [
        rf"(?:tren|lon hon|it nhat|toi thieu|min|tu)\s*(\d+[\d\.,]*\s*{unit})",
        rf">\s*(\d+[\d\.,]*\s*{unit})",
    ]

    for pattern in max_patterns:
        match = re.search(pattern, text_norm)
        if match:
            max_price = _parse_money_number(match.group(1))
            break

    range_match = re.search(
        rf"(?:tu)\s*(\d+[\d\.,]*\s*{unit})\s*(?:den|toi|-)\s*(\d+[\d\.,]*\s*{unit})",
        text_norm,
    )
    if range_match:
        min_price = _parse_money_number(range_match.group(1))
        max_price = _parse_money_number(range_match.group(2))
        return min_price, max_price

    for pattern in min_patterns:
        match = re.search(pattern, text_norm)
        if match:
            min_price = _parse_money_number(match.group(1))
            break

    return min_price, max_price


def _extract_requested_count(message: str) -> Optional[int]:
    text_norm = normalize_text(message)
    match = re.search(r"\b(\d{1,2})\s*(?:cuon|quyen|sach|tac pham)\b", text_norm)
    if match:
        try:
            value = int(match.group(1))
            if 1 <= value <= 20:
                return value
        except ValueError:
            return None
    return None


def _extract_sort_intent(message: str) -> Optional[str]:
    text_norm = normalize_text(message)

    if any(k in text_norm for k in ["dat nhat", "cao nhat", "max gia", "gia cao nhat"]):
        return "highest_price"
    if any(k in text_norm for k in ["re nhat", "thap nhat", "min gia", "gia thap nhat"]):
        return "lowest_price"
    if any(k in text_norm for k in ["ban chay nhat", "nhieu nguoi mua", "pho bien nhat"]):
        return "best_seller"
    return None


def _extract_category_preferences(message: str) -> Set[str]:
    text_norm = normalize_text(message)
    preferred: Set[str] = set()

    def _contains_keyword(keyword: str) -> bool:
        key = normalize_text(keyword)
        if " " in key:
            return key in text_norm
        return re.search(rf"\b{re.escape(key)}\b", text_norm) is not None

    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(_contains_keyword(kw) for kw in keywords):
            preferred.add(category)
    return preferred


def _extract_author_preferences(message: str, known_authors: Set[str]) -> Set[str]:
    text_norm = normalize_text(message)
    query_tokens = {
        t for t in re.findall(r"[a-z0-9]+", text_norm) if len(t) >= 2 and t not in STOPWORDS
    }
    preferred: Set[str] = set()

    patterns = [
        r"tac\s*gia\s+([a-z0-9\s\.]+)",
        r"sach\s+cua\s+([a-z0-9\s\.]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text_norm)
        if match:
            candidate = re.sub(r"\s+", " ", match.group(1)).strip(" .")
            candidate = re.sub(r"\b(khong|ko|ha|a|nhi|nhe|duoc\s*khong)\b$", "", candidate).strip()
            if len(candidate) >= 4:
                preferred.add(candidate)

    # If user types author name directly, map it to known authors from KB.
    for author in known_authors:
        author_norm = normalize_text(author)
        tokens = [
            t for t in re.findall(r"[a-z0-9]+", author_norm) if len(t) >= 2 and t not in STOPWORDS
        ]
        if len(tokens) < 2:
            continue
        if all(t in query_tokens for t in tokens):
            preferred.add(author_norm)

    return preferred


def _query_keywords(message: str) -> Set[str]:
    keywords = set(tokenize(message))
    return {kw for kw in keywords if len(kw) >= 3 and kw not in STOPWORDS}


def _parse_metadata(raw_value: Optional[str]) -> Dict[str, Any]:
    if not raw_value:
        return {}
    try:
        data = json.loads(raw_value)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _metadata_price(meta: Dict[str, Any]) -> Optional[float]:
    raw = meta.get("price")
    if raw is None:
        return None
    return _parse_money_number(str(raw))


def _format_vnd(price: Optional[float]) -> str:
    if price is None:
        return "không rõ giá"
    return f"{int(round(price)):,}đ".replace(",", ".")


def _book_detail_url(meta: Dict[str, Any]) -> Optional[str]:
    book_id = meta.get("book_id")
    if book_id is None:
        return None
    base = BOOK_DETAIL_BASE_URL.rstrip("/")
    if not base:
        return f"/books/{book_id}"
    return f"{base}/books/{book_id}"


def _is_book_related(message: str) -> bool:
    normalized = normalize_text(message)
    return any(kw in normalized for kw in BOOK_INTENT_KEYWORDS)


def _build_context_snapshot(message: str, citations: List[SearchResult]) -> Dict[str, Any]:
    return {
        "message": message,
        "book_related": _is_book_related(message),
        "timestamp": datetime.utcnow().isoformat(),
        "citations": [c.model_dump() for c in citations],
    }


def _build_general_answer(message: str) -> Optional[str]:
    normalized = normalize_text(message)
    now = datetime.now()

    if "hom nay" in normalized and ("ngay" in normalized or "thu" in normalized):
        weekdays = {
            0: "Thứ Hai",
            1: "Thứ Ba",
            2: "Thứ Tư",
            3: "Thứ Năm",
            4: "Thứ Sáu",
            5: "Thứ Bảy",
            6: "Chủ Nhật",
        }
        weekday_label = weekdays.get(now.weekday(), "Hôm nay")
        return f"Hôm nay là {weekday_label}, ngày {now.strftime('%d/%m/%Y')}."

    if "may gio" in normalized or "gio" in normalized:
        return f"Hiện tại là {now.strftime('%H:%M')} (giờ hệ thống)."

    if any(token in normalized for token in ["xin chao", "chao", "hello", "hi"]):
        return "Chào bạn, mình có thể hỗ trợ cả câu hỏi ngắn general và tư vấn sách chi tiết khi bạn cần."

    return None


def _is_book_intent(message: str, citations: List[SearchResult]) -> bool:
    text_norm = normalize_text(message)
    min_price, max_price = _extract_price_constraints(message)
    preferred_categories = _extract_category_preferences(message)
    known_authors = {
        str((c.metadata or {}).get("author") or "").strip()
        for c in citations
        if (c.metadata or {}).get("author")
    }
    preferred_authors = _extract_author_preferences(message, known_authors)

    if min_price is not None or max_price is not None:
        return True
    if preferred_categories or preferred_authors:
        return True
    if any(kw in text_norm for kw in BOOK_INTENT_KEYWORDS):
        return True
    if citations and not any(word in text_norm for word in ["hom nay", "may gio", "thoi tiet", "xin chao"]):
        return True
    return False


def _is_category_match(meta: Dict[str, Any], preferred_categories: Set[str]) -> bool:
    if not preferred_categories:
        return False
    category_norm = normalize_text(str(meta.get("category") or ""))
    return any(normalize_text(cat) == category_norm for cat in preferred_categories)


def _is_author_match(meta: Dict[str, Any], preferred_authors: Set[str]) -> bool:
    if not preferred_authors:
        return False
    author_norm = normalize_text(str(meta.get("author") or ""))
    if not author_norm:
        return False

    author_tokens = [t for t in re.findall(r"[a-z0-9]+", author_norm) if len(t) >= 2 and t not in STOPWORDS]
    if len(author_tokens) < 2:
        return False

    for pref in preferred_authors:
        pref_norm = normalize_text(pref)
        pref_tokens = [
            t for t in re.findall(r"[a-z0-9]+", pref_norm) if len(t) >= 2 and t not in STOPWORDS
        ]
        if len(pref_tokens) < 2:
            continue

        if author_norm == pref_norm:
            return True

        overlap = len(set(author_tokens) & set(pref_tokens))
        same_last_name = author_tokens[-1] == pref_tokens[-1]
        if same_last_name and overlap >= 2:
            return True

    return False


def build_tf_vector(text_value: str) -> Dict[str, float]:
    tokens = tokenize(text_value)
    if not tokens:
        return {}

    vec: Dict[str, float] = {}
    token_count = float(len(tokens))
    for token in tokens:
        vec[token] = vec.get(token, 0.0) + (1.0 / token_count)
    return vec


def vector_norm(vec: Dict[str, float]) -> float:
    n = math.sqrt(sum(v * v for v in vec.values()))
    return n if n > 0 else 1.0


def cosine_similarity(a: Dict[str, float], b: Dict[str, float], norm_a: float, norm_b: float) -> float:
    if not a or not b:
        return 0.0
    shared = set(a.keys()) & set(b.keys())
    if not shared:
        return 0.0
    dot = sum(a[t] * b[t] for t in shared)
    return dot / (norm_a * norm_b)


def chunk_text(content: str, chunk_size: int = 500) -> List[str]:
    cleaned = re.sub(r"\s+", " ", content or "").strip()
    if not cleaned:
        return []
    chunks: List[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        chunks.append(cleaned[start:end])
        start = end
    return chunks


def fetch_books() -> List[dict]:
    try:
        with httpx.Client(base_url=BOOK_SERVICE_URL, timeout=8) as client:
            res = client.get("/api/books/")
            res.raise_for_status()
            data = res.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and isinstance(data.get("results"), list):
                return data["results"]
    except Exception:
        return []
    return []


def fetch_order_stats() -> Dict[int, float]:
    popularity: Dict[int, float] = {}
    try:
        with httpx.Client(base_url=ORDER_SERVICE_URL, timeout=8) as client:
            res = client.get("/api/orders")
            if res.status_code != 200:
                return popularity
            orders = res.json()
            if not isinstance(orders, list):
                return popularity
            for order in orders:
                items = order.get("items") if isinstance(order, dict) else None
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    try:
                        bid = int(item.get("book_id"))
                        qty = float(item.get("quantity") or 0)
                    except (TypeError, ValueError):
                        continue
                    if qty > 0:
                        popularity[bid] = popularity.get(bid, 0.0) + qty
    except Exception:
        return popularity
    return popularity


def upsert_document_and_chunks(db: Session, source_type: str, source_id: str, title: str, content: str, metadata: dict) -> int:
    doc_id = f"{source_type}:{source_id}"
    now = datetime.utcnow()

    existing_doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if existing_doc:
        existing_doc.title = title
        existing_doc.content = content
        existing_doc.metadata_json = json.dumps(metadata)
        existing_doc.updated_at = now
    else:
        db.add(
            KnowledgeDocument(
                id=doc_id,
                source_type=source_type,
                source_id=source_id,
                title=title,
                content=content,
                metadata_json=json.dumps(metadata),
                updated_at=now,
            )
        )

    db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc_id).delete()

    chunks = chunk_text(content)
    for idx, text_value in enumerate(chunks):
        vec = build_tf_vector(text_value)
        db.add(
            KnowledgeChunk(
                id=f"{doc_id}:chunk:{idx}",
                document_id=doc_id,
                chunk_index=idx,
                text=text_value,
                token_count=len(tokenize(text_value)),
                norm=vector_norm(vec),
                vector_json=json.dumps(vec),
                metadata_json=json.dumps(metadata),
                updated_at=now,
            )
        )

    return len(chunks)


@app.post("/api/chatbot/ingest/books", response_model=IngestResponse)
def ingest_books():
    db: Session = SessionLocal()
    try:
        books = fetch_books()
        popularity = fetch_order_stats()
        docs = 0
        chunks = 0
        for book in books:
            bid = book.get("id")
            if bid is None:
                continue
            title = str(book.get("title") or f"Book {bid}")
            author = str(book.get("author") or "Unknown")
            category = str(book.get("category") or "Unknown")
            description = str(book.get("description") or "")
            price = str(book.get("price") or "")
            stock = str(book.get("stock") or "")
            sold_qty = popularity.get(int(bid), 0.0)

            content = (
                f"Tiêu đề: {title}. "
                f"Tác giả: {author}. "
                f"Thể loại: {category}. "
                f"Mô tả: {description}. "
                f"Giá: {price}. "
                f"Tồn kho: {stock}. "
                f"Đã bán: {sold_qty}."
            )
            metadata = {
                "book_id": bid,
                "title": title,
                "author": author,
                "category": category,
                "price": price,
                "stock": stock,
                "sold_qty": sold_qty,
            }
            chunks += upsert_document_and_chunks(
                db=db,
                source_type="book",
                source_id=str(bid),
                title=title,
                content=content,
                metadata=metadata,
            )
            docs += 1

        db.commit()
        return IngestResponse(ok=True, documents_upserted=docs, chunks_upserted=chunks)
    finally:
        db.close()


@app.get("/api/chatbot/search", response_model=List[SearchResult])
def search(query: str, top_k: int = 5):
    if not query.strip():
        return []

    db: Session = SessionLocal()
    try:
        min_price, max_price = _extract_price_constraints(query)
        sort_intent = _extract_sort_intent(query)
        requested_count = _extract_requested_count(query)
        preferred_categories = _extract_category_preferences(query)
        query_terms = _query_keywords(query)

        query_vec = build_tf_vector(query)
        query_norm = vector_norm(query_vec)
        rows = db.query(KnowledgeChunk).all()
        known_authors: Set[str] = set()
        for row in rows:
            metadata = _parse_metadata(row.metadata_json)
            author = str(metadata.get("author") or "").strip()
            if author:
                known_authors.add(author)
        preferred_authors = _extract_author_preferences(query, known_authors)

        scored: List[SearchResult] = []
        for row in rows:
            try:
                chunk_vec = json.loads(row.vector_json)
                if not isinstance(chunk_vec, dict):
                    continue
                vec = {str(k): float(v) for k, v in chunk_vec.items()}
            except Exception:
                continue

            score = cosine_similarity(query_vec, vec, query_norm, float(row.norm or 1.0))
            if score <= 0 and not sort_intent:
                continue

            metadata = _parse_metadata(row.metadata_json)
            category = str(metadata.get("category") or "")
            category_norm = normalize_text(category)
            title_norm = normalize_text(str(metadata.get("title") or ""))
            author_norm = normalize_text(str(metadata.get("author") or ""))

            price_value = _metadata_price(metadata)
            if min_price is not None and price_value is not None and price_value < min_price:
                continue
            if max_price is not None and price_value is not None and price_value > max_price:
                continue

            if preferred_categories:
                category_match = any(normalize_text(cat) == category_norm for cat in preferred_categories)
                if category_match:
                    score += 0.24
                else:
                    score *= 0.72

            if preferred_authors:
                author_match = _is_author_match(metadata, preferred_authors)
                if author_match:
                    score += 0.30
                else:
                    score *= 0.65

            if query_terms:
                title_author_space = f"{title_norm} {author_norm}"
                overlap = sum(1 for term in query_terms if term in title_author_space)
                if overlap > 0:
                    score += min(0.18, overlap * 0.06)

            sold_qty = float(metadata.get("sold_qty") or 0.0)
            if sold_qty > 0:
                score += min(0.12, math.log1p(sold_qty) * 0.03)

            doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == row.document_id).first()
            title = doc.title if doc else row.document_id
            snippet = row.text[:180]
            scored.append(
                SearchResult(
                    chunk_id=row.id,
                    score=round(score, 4),
                    document_id=row.document_id,
                    title=title,
                    snippet=snippet,
                    detail_url=_book_detail_url(metadata),
                    metadata=metadata,
                )
            )

        dedup: Dict[str, SearchResult] = {}
        for item in scored:
            current = dedup.get(item.document_id)
            if not current or item.score > current.score:
                dedup[item.document_id] = item

        scored = list(dedup.values())
        if not scored and _is_book_related(query):
            # Fallback for vague prompts like "sach hay": return popular in-stock books.
            fallback_map: Dict[str, SearchResult] = {}
            for row in rows:
                metadata = _parse_metadata(row.metadata_json)
                if not metadata:
                    continue
                stock_raw = metadata.get("stock")
                try:
                    stock_val = float(stock_raw) if stock_raw is not None else 0.0
                except (TypeError, ValueError):
                    stock_val = 0.0
                if stock_val <= 0:
                    continue

                doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == row.document_id).first()
                title = doc.title if doc else row.document_id
                candidate = SearchResult(
                    chunk_id=row.id,
                    score=0.0,
                    document_id=row.document_id,
                    title=title,
                    snippet=row.text[:180],
                    detail_url=_book_detail_url(metadata),
                    metadata=metadata,
                )

                existing = fallback_map.get(candidate.document_id)
                if not existing:
                    fallback_map[candidate.document_id] = candidate

            scored = list(fallback_map.values())
            scored.sort(
                key=lambda x: (
                    float((x.metadata or {}).get("sold_qty") or 0.0),
                    _metadata_price(x.metadata or {}) or 0.0,
                ),
                reverse=True,
            )

        if preferred_authors:
            strict_author = [
                item for item in scored if _is_author_match(item.metadata or {}, preferred_authors)
            ]
            if strict_author:
                scored = strict_author
            else:
                scored = []
        if preferred_categories:
            strict_category = [
                item for item in scored if _is_category_match(item.metadata or {}, preferred_categories)
            ]
            if strict_category:
                scored = strict_category

        if sort_intent == "highest_price":
            scored.sort(key=lambda x: _metadata_price(x.metadata or {}) or -1.0, reverse=True)
        elif sort_intent == "lowest_price":
            scored.sort(key=lambda x: _metadata_price(x.metadata or {}) or float("inf"))
        elif sort_intent == "best_seller":
            scored.sort(key=lambda x: float((x.metadata or {}).get("sold_qty") or 0.0), reverse=True)
        else:
            scored.sort(key=lambda x: x.score, reverse=True)

        final_limit = requested_count or top_k
        return scored[: max(1, min(final_limit, 20))]
    finally:
        db.close()


def _build_answer(message: str, citations: List[SearchResult]) -> str:
    min_price, max_price = _extract_price_constraints(message)
    preferred_categories = _extract_category_preferences(message)
    known_authors = {
        str((c.metadata or {}).get("author") or "").strip() for c in citations if (c.metadata or {}).get("author")
    }
    preferred_authors = _extract_author_preferences(message, known_authors)

    if not citations:
        if not _is_book_related(message):
            general = _build_general_answer(message)
            if general:
                return general
            return (
                "Mình ưu tiên tư vấn sách, nhưng vẫn hỗ trợ câu hỏi general ngắn gọn. "
                "Với câu này mình chưa có đủ ngữ cảnh để trả lời chắc chắn, bạn có thể hỏi cụ thể hơn nhé."
            )

        condition_parts: List[str] = []
        if preferred_categories:
            condition_parts.append(f"thể loại: {', '.join(sorted(preferred_categories))}")
        if preferred_authors:
            display_authors = sorted({a.title() for a in preferred_authors})
            condition_parts.append(f"tác giả: {', '.join(display_authors)}")
        if min_price is not None:
            condition_parts.append(f"giá từ {_format_vnd(min_price)}")
        if max_price is not None:
            condition_parts.append(f"giá đến {_format_vnd(max_price)}")

        if condition_parts:
            requested = "; ".join(condition_parts)
            return (
                "Hiện tại chưa có sách đáp ứng yêu cầu của bạn. "
                f"Yêu cầu đã ghi nhận: {requested}. "
                "Bạn có muốn mình nới điều kiện một chút để mình gợi ý phương án gần nhất không?"
            )

        return (
            "Hiện tại chưa có sách đáp ứng yêu cầu của bạn. "
            f"Yêu cầu đã ghi nhận: \"{message.strip()}\". "
            "Bạn có thể nói rõ hơn về thể loại, mức giá (ví dụ: dưới 200k), hoặc tác giả mong muốn nhé."
        )

    requested_count = _extract_requested_count(message) or 3
    top = citations[: max(1, min(requested_count, 20))]
    lines = ["Mình đã lọc theo yêu cầu của bạn và gợi ý nhanh như sau:"]

    for c in top:
        meta = c.metadata or {}
        author = str(meta.get("author") or "Không rõ tác giả")
        category = str(meta.get("category") or "Không rõ thể loại")
        price = _metadata_price(meta)
        detail_url = c.detail_url or _book_detail_url(meta)
        lines.append(
            f"- {c.title} | {author} | {category} | {_format_vnd(price)}"
        )
        if detail_url:
            lines.append(f"  Xem chi tiết: {detail_url}")

    condition_parts: List[str] = []
    if preferred_categories:
        condition_parts.append(f"thể loại: {', '.join(sorted(preferred_categories))}")
    if preferred_authors:
        display_authors = sorted({a.title() for a in preferred_authors})
        condition_parts.append(f"tác giả: {', '.join(display_authors)}")
    if min_price is not None:
        condition_parts.append(f"giá từ {_format_vnd(min_price)}")
    if max_price is not None:
        condition_parts.append(f"giá đến {_format_vnd(max_price)}")
    if condition_parts:
        lines.append(f"Điều kiện đã áp dụng: {'; '.join(condition_parts)}.")

    lines.append("Nếu bạn muốn, mình lọc tiếp theo mức giá sát hơn hoặc theo một tác giả cụ thể.")
    return "\n".join(lines)


def _build_context_for_llm(message: str, citations: List[SearchResult]) -> str:
    context_blocks = []
    for idx, item in enumerate(citations[:MAX_CONTEXT_CHUNKS], start=1):
        meta = item.metadata or {}
        context_blocks.append(
            "[{}] title={}; author={}; category={}; price={}; sold_qty={}; snippet={}; score={}".format(
                idx,
                item.title,
                meta.get("author", ""),
                meta.get("category", ""),
                meta.get("price", ""),
                meta.get("sold_qty", ""),
                item.snippet,
                item.score,
            )
        )
    joined = "\n".join(context_blocks)
    if not joined:
        joined = "(không có context sách phù hợp trực tiếp cho câu hỏi này)"
    return (
        "Bạn là trợ lý thông minh cho website thương mại điện tử sách. "
        "Ưu tiên tuyệt đối câu trả lời liên quan sách và dữ liệu context đã cung cấp. "
        "Nếu câu hỏi là general (không liên quan sách), vẫn được trả lời ngắn gọn 1-3 câu bằng tiếng Việt. "
        "Không bịa các dữ kiện cụ thể về sách nếu context không có.\n\n"
        f"Context:\n{joined}\n\n"
        f"Câu hỏi người dùng: {message}\n"
        "Yêu cầu trả lời: ngắn gọn bằng tiếng Việt. Nếu có sách phù hợp thì gợi ý 2-3 sách và thêm link chi tiết khi có."
    )


def _generate_answer_with_llm(message: str, citations: List[SearchResult]) -> Optional[str]:
    if not LLM_API_BASE_URL or not LLM_API_KEY:
        return None

    prompt = _build_context_for_llm(message, citations)
    request_payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "Bạn là chatbot tư vấn sách chính xác và hữu ích."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": max(64, min(LLM_MAX_TOKENS, 512)),
    }

    try:
        with httpx.Client(timeout=LLM_TIMEOUT) as client:
            res = client.post(
                f"{LLM_API_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
            )
            if res.status_code != 200:
                return None
            data = res.json()
            choices = data.get("choices") if isinstance(data, dict) else None
            if not choices or not isinstance(choices, list):
                return None
            message_obj = choices[0].get("message") if isinstance(choices[0], dict) else None
            if not isinstance(message_obj, dict):
                return None
            content = str(message_obj.get("content") or "").strip()
            return content or None
    except Exception:
        return None


@app.post("/api/chatbot/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    db: Session = SessionLocal()
    try:
        if db.query(KnowledgeChunk).count() == 0:
            ingest_books()

        if payload.session_id:
            session = db.query(ChatSession).filter(ChatSession.id == payload.session_id).first()
            if not session:
                session = ChatSession(id=payload.session_id, customer_id=payload.customer_id, updated_at=datetime.utcnow())
                db.add(session)
        else:
            session = ChatSession(id=str(uuid4()), customer_id=payload.customer_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
            db.add(session)

        book_related = _is_book_related(payload.message)
        citations = (
            search(query=payload.message, top_k=min(payload.top_k, MAX_CONTEXT_CHUNKS))
            if book_related
            else []
        )

        if _is_book_intent(payload.message, citations):
            answer = _build_answer(payload.message, citations)
        else:
            answer = _generate_answer_with_llm(payload.message, citations) or _build_answer(payload.message, citations)
        context_snapshot = _build_context_snapshot(payload.message, citations)

        user_msg = ChatMessage(
            id=str(uuid4()),
            session_id=session.id,
            role="user",
            content=payload.message,
            created_at=datetime.utcnow(),
        )
        bot_msg = ChatMessage(
            id=str(uuid4()),
            session_id=session.id,
            role="assistant",
            content=answer,
            citations_json=json.dumps([c.model_dump() for c in citations]),
            context_json=json.dumps(context_snapshot),
            created_at=datetime.utcnow(),
        )
        session.updated_at = datetime.utcnow()
        db.add(user_msg)
        db.add(bot_msg)
        db.commit()

        return ChatResponse(session_id=session.id, answer=answer, citations=citations)
    finally:
        db.close()


@app.post("/api/chatbot/feedback")
def feedback(payload: FeedbackRequest):
    db: Session = SessionLocal()
    try:
        db.add(
            ChatFeedback(
                id=str(uuid4()),
                message_id=payload.message_id,
                customer_id=payload.customer_id,
                score=payload.score,
                comment=payload.comment,
                created_at=datetime.utcnow(),
            )
        )
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/api/chatbot/sessions/{session_id}/messages", response_model=List[ChatMessageOut])
def session_messages(session_id: str, limit: int = 30):
    db: Session = SessionLocal()
    try:
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(max(1, min(limit, 200)))
            .all()
        )

        out: List[ChatMessageOut] = []
        for row in rows:
            citations = []
            try:
                raw = json.loads(row.citations_json) if row.citations_json else []
                if isinstance(raw, list):
                    citations = [SearchResult(**item) for item in raw if isinstance(item, dict)]
            except Exception:
                citations = []

            out.append(
                ChatMessageOut(
                    id=row.id,
                    role=row.role,
                    content=row.content,
                    citations=citations,
                    created_at=row.created_at,
                )
            )
        return out
    finally:
        db.close()


@app.delete("/api/chatbot/sessions/{session_id}")
def delete_session(session_id: str):
    db: Session = SessionLocal()
    try:
        db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
        db.query(ChatSession).filter(ChatSession.id == session_id).delete()
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/api/chatbot/health")
def health():
    return {
        "service": "chatbot-service",
        "status": "ok",
        "db_url": DB_URL,
        "book_service": BOOK_SERVICE_URL,
        "order_service": ORDER_SERVICE_URL,
        "llm_configured": bool(LLM_API_BASE_URL and LLM_API_KEY),
        "llm_model": LLM_MODEL,
    }
