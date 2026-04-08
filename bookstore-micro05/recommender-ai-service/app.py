import json
import importlib
import math
import os
import re
import threading
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Tuple
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

SentenceTransformer = None

app = FastAPI(title="Recommender AI Service")

DB_URL = os.getenv(
    "DB_URL",
    "mysql+pymysql://root:123456@host.docker.internal:3306/recommender_db",
)
BOOK_SERVICE_URL = os.getenv("BOOK_SERVICE_URL", "http://book-service:8000")
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8000")


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
    viewed_book_counts = Column(Text, nullable=True)
    purchased_book_counts = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class KnowledgeVectorRow(Base):
    __tablename__ = "recommender_knowledge_vectors"

    id = Column(String(128), primary_key=True)
    entity_type = Column(String(32), nullable=False, index=True)
    entity_id = Column(String(64), nullable=False, index=True)
    vector_json = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


def ensure_recommender_schema():
    db_name = make_url(DB_URL).database

    def _column_exists(conn: Session, table_name: str, column_name: str) -> bool:
        if not db_name:
            return False
        result = conn.execute(
            text(
                """
                SELECT 1
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = :db_name
                  AND TABLE_NAME = :table_name
                  AND COLUMN_NAME = :column_name
                LIMIT 1
                """
            ),
            {
                "db_name": db_name,
                "table_name": table_name,
                "column_name": column_name,
            },
        ).first()
        return result is not None

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS recommender_user_preferences (
                    customer_id INT PRIMARY KEY,
                    viewed_book_ids TEXT NOT NULL,
                    viewed_book_counts TEXT NULL,
                    purchased_book_counts TEXT NULL,
                    updated_at DATETIME NULL
                )
                """
            )
        )
        if not _column_exists(conn, "recommender_user_preferences", "viewed_book_counts"):
            conn.execute(
                text(
                    "ALTER TABLE recommender_user_preferences "
                    "ADD COLUMN viewed_book_counts TEXT NULL"
                )
            )
        if not _column_exists(conn, "recommender_user_preferences", "purchased_book_counts"):
            conn.execute(
                text(
                    "ALTER TABLE recommender_user_preferences "
                    "ADD COLUMN purchased_book_counts TEXT NULL"
                )
            )


ensure_recommender_schema()


class RecommendRequest(BaseModel):
    customer_id: int
    viewed_book_ids: List[int] = []
    recent_viewed_book_ids: List[int] = []
    purchased_book_ids: List[int] = []
    strict_franchise_only: bool = False
    explore_mode: bool = False


class Recommendation(BaseModel):
    book_id: int
    score: float
    reason: str


class TrackViewRequest(BaseModel):
    customer_id: int
    book_id: int


class ChatRequest(BaseModel):
    customer_id: int
    message: str
    top_k: int = 3
    history: List[dict] = Field(default_factory=list)


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatResponse(BaseModel):
    answer: str
    retrieved_products: List[dict]
    model_source: str
    retrieval_count: int = 0


BOOK_POOL = [
    {"book_id": 1, "title": "Classic Fiction", "author": "Unknown", "description": "classic story fiction"},
    {"book_id": 2, "title": "Python Engineering", "author": "Unknown", "description": "technology python software"},
    {"book_id": 3, "title": "Startup Business", "author": "Unknown", "description": "business startup strategy"},
    {"book_id": 4, "title": "Mystery Tale", "author": "Unknown", "description": "fiction mystery detective"},
    {"book_id": 5, "title": "AI Fundamentals", "author": "Unknown", "description": "technology ai machine learning"},
    {"book_id": 6, "title": "Growth Mindset", "author": "Unknown", "description": "self help growth habit"},
]


def tokenize(text_value: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text_value or "").lower())


EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "64"))
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
_embedding_lock = threading.Lock()
_embedding_model = None
_deep_model_lock = threading.Lock()
_deep_model = None
_deep_model_error = None
DEEP_MODEL_DIR = os.getenv("DEEP_MODEL_DIR", os.path.join(os.path.dirname(__file__), "models"))
DEEP_MODEL_ENABLED = os.getenv("DEEP_MODEL_ENABLED", "true").strip().lower() not in {"0", "false", "no"}


def _get_embedding_model():
    global _embedding_model
    global SentenceTransformer

    if SentenceTransformer is None:
        try:
            module = importlib.import_module("sentence_transformers")
            SentenceTransformer = getattr(module, "SentenceTransformer", None)
        except Exception:
            SentenceTransformer = None

    if SentenceTransformer is None:
        return None
    if _embedding_model is not None:
        return _embedding_model

    with _embedding_lock:
        if _embedding_model is None:
            _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def _load_deep_model():
    global _deep_model
    global _deep_model_error

    if not DEEP_MODEL_ENABLED:
        return None
    if _deep_model is not None:
        return _deep_model
    if _deep_model_error is not None:
        return None

    with _deep_model_lock:
        if _deep_model is not None:
            return _deep_model
        if _deep_model_error is not None:
            return None

        model_file = os.path.join(DEEP_MODEL_DIR, "ncf_graph_model.h5")
        if not os.path.exists(model_file):
            _deep_model_error = f"Missing model file: {model_file}"
            return None

        try:
            module = importlib.import_module("deep_learning_model")
            model_cls = getattr(module, "NCFGraphRecommenderModel")
            deep_model = model_cls(embedding_dim=64, num_users=300, num_items=2000)
            deep_model.load(DEEP_MODEL_DIR)
            if deep_model.model is None:
                _deep_model_error = "Deep model loaded without model graph"
                return None
            _deep_model = deep_model
            return _deep_model
        except Exception as ex:
            _deep_model_error = str(ex)
            return None


def _build_deep_context_feature(
    candidate_id: int,
    seen: set[int],
    view_counts: Dict[int, float],
    purchase_counts: Dict[int, float],
    popularity: Dict[int, float],
    max_popularity: float,
) -> List[float]:
    user_history_size = len(seen)
    item_popularity = popularity.get(candidate_id, 0.0)
    interaction_count = view_counts.get(candidate_id, 0.0) + purchase_counts.get(candidate_id, 0.0)
    user_diversity = len(seen)
    time_factor = min(interaction_count / 5.0, 1.0)
    strength = min((0.3 * view_counts.get(candidate_id, 0.0)) + (0.8 * purchase_counts.get(candidate_id, 0.0)), 1.0)

    if max_popularity > 0:
        normalized_popularity = min(item_popularity / max_popularity, 1.0)
    else:
        normalized_popularity = 0.0

    return [
        min(user_history_size / 50.0, 1.0),
        normalized_popularity,
        min(interaction_count / 3.0, 1.0),
        min(user_diversity / 50.0, 1.0),
        time_factor,
        math.tanh(user_history_size / 50.0),
        math.tanh(normalized_popularity),
        strength,
    ]


def _predict_deep_scores(
    customer_id: int,
    candidate_ids: List[int],
    seen: set[int],
    view_counts: Dict[int, float],
    purchase_counts: Dict[int, float],
    popularity: Dict[int, float],
    max_popularity: float,
) -> Dict[int, float]:
    deep_model = _load_deep_model()
    if deep_model is None:
        return {}

    if customer_id <= 0 or customer_id > deep_model.num_users:
        return {}

    valid_ids = [cid for cid in candidate_ids if 0 < cid <= deep_model.num_items]
    if not valid_ids:
        return {}

    user_ids = [customer_id] * len(valid_ids)
    context_features = [
        _build_deep_context_feature(
            candidate_id=cid,
            seen=seen,
            view_counts=view_counts,
            purchase_counts=purchase_counts,
            popularity=popularity,
            max_popularity=max_popularity,
        )
        for cid in valid_ids
    ]

    try:
        predictions = deep_model.predict_batch(user_ids, valid_ids, context_features)
        return {cid: float(score) for cid, score in zip(valid_ids, predictions)}
    except Exception:
        return {}


def _normalize_dense(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0:
        return vec
    return [v / norm for v in vec]


def _hash_embedding(text_value: str, dim: int = EMBEDDING_DIM) -> List[float]:
    vec = [0.0] * max(8, dim)
    tokens = tokenize(text_value)
    if not tokens:
        return vec

    for token in tokens:
        idx = abs(hash(token)) % len(vec)
        sign = 1.0 if (hash(token + "_sign") % 2 == 0) else -1.0
        vec[idx] += sign

    return _normalize_dense(vec)


def encode_text_embedding(text_value: str) -> tuple[List[float], str]:
    model = _get_embedding_model()
    if model is None:
        return _hash_embedding(text_value), "hash-fallback"

    try:
        embedding = model.encode([text_value], normalize_embeddings=True)[0]
        return [float(x) for x in embedding.tolist()], "transformer"
    except Exception:
        return _hash_embedding(text_value), "hash-fallback"


def cosine_similarity_dense(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    if size == 0:
        return 0.0
    return float(sum(a[i] * b[i] for i in range(size)))


def _to_int(raw_value: object) -> Optional[int]:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _safe_json_dict(raw: Optional[str]) -> Dict[str, object]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def upsert_knowledge_vector(
    db: Session,
    entity_type: str,
    entity_id: str,
    vector: List[float],
    metadata: Optional[Dict[str, object]] = None,
) -> None:
    row_id = f"{entity_type}:{entity_id}"
    now = datetime.utcnow()
    existing = db.query(KnowledgeVectorRow).filter(KnowledgeVectorRow.id == row_id).first()
    if existing:
        existing.vector_json = json.dumps(vector)
        existing.metadata_json = json.dumps(metadata or {})
        existing.updated_at = now
    else:
        db.add(
            KnowledgeVectorRow(
                id=row_id,
                entity_type=entity_type,
                entity_id=entity_id,
                vector_json=json.dumps(vector),
                metadata_json=json.dumps(metadata or {}),
                updated_at=now,
            )
        )


def build_behavior_text(customer_id: int, viewed_ids: List[int], view_counts: Dict[int, float], purchase_counts: Dict[int, float]) -> str:
    tokens = [f"user_{customer_id}"]
    for bid in viewed_ids[-30:]:
        tokens.append(f"view_book_{bid}")
    for bid, cnt in sorted(view_counts.items(), key=lambda x: x[1], reverse=True)[:30]:
        tokens.append(f"view_count_{bid}_{int(cnt)}")
    for bid, cnt in sorted(purchase_counts.items(), key=lambda x: x[1], reverse=True)[:30]:
        tokens.append(f"purchase_count_{bid}_{int(cnt)}")
    return " ".join(tokens)


def sync_product_vectors(db: Session, books: List[dict]) -> str:
    model_source = "hash-fallback"
    for book in books:
        raw_id = book.get("id", book.get("book_id"))
        book_id = _to_int(raw_id)
        if book_id is None:
            continue
        product_text = _build_text_from_book(book)
        vector, source = encode_text_embedding(product_text)
        model_source = source
        upsert_knowledge_vector(
            db=db,
            entity_type="product",
            entity_id=str(book_id),
            vector=vector,
            metadata={
                "book_id": book_id,
                "title": book.get("title") or "",
                "author": book.get("author") or "",
                "category": book.get("category") or "",
                "description": book.get("description") or "",
                "price": book.get("price"),
            },
        )
    return model_source


def retrieve_top_products(db: Session, user_vector: List[float], top_k: int = 3) -> List[dict]:
    rows = (
        db.query(KnowledgeVectorRow)
        .filter(KnowledgeVectorRow.entity_type == "product")
        .all()
    )
    scored: List[dict] = []
    for row in rows:
        try:
            vector = json.loads(row.vector_json)
            if not isinstance(vector, list):
                continue
            product_vector = [float(v) for v in vector]
        except (ValueError, TypeError):
            continue

        score = cosine_similarity_dense(user_vector, product_vector)
        metadata = _safe_json_dict(row.metadata_json)
        metadata["score"] = round(score, 4)
        scored.append(metadata)

    scored.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    return scored[: max(1, min(top_k, 10))]


def _keyword_overlap_score(query_tokens: set[str], product: Dict[str, object]) -> float:
    if not query_tokens:
        return 0.0

    product_tokens = _product_tokens(product)
    if not product_tokens:
        return 0.0

    overlap = len(query_tokens & product_tokens)
    if overlap <= 0:
        return 0.0
    return overlap / max(1.0, float(len(query_tokens)))


def _extract_focus_tokens(message: str) -> set[str]:
    stopwords = {
        "toi", "mình", "minh", "ban", "cho", "xin", "tu", "van", "sach", "book", "hello", "hi", "la", "ve",
        "the", "loai", "gia", "hoc", "tap", "muc", "tieu", "cua", "toi", "nhung", "can", "tim",
    }
    tokens = set(tokenize(message))
    return {token for token in tokens if len(token) >= 2 and token not in stopwords}


def _product_tokens(product: Dict[str, object]) -> set[str]:
    text_parts = [
        str(product.get("title") or ""),
        str(product.get("author") or ""),
        str(product.get("category") or ""),
        str(product.get("description") or ""),
    ]
    return set(tokenize(" ".join(text_parts)))


def filter_retrieved_by_query_tokens(message: str, retrieved: List[dict]) -> List[dict]:
    query_tokens = _extract_focus_tokens(message)
    if not query_tokens:
        return retrieved

    matched: List[dict] = []
    for item in retrieved:
        if _product_tokens(item) & query_tokens:
            matched.append(item)

    return matched if matched else retrieved


def _normalize_chat_history(history: List[dict], limit: int = 8) -> List[ChatTurn]:
    normalized: List[ChatTurn] = []
    for item in history[-limit:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append(ChatTurn(role=role, content=content[:500]))
    return normalized


def _is_follow_up_question(message: str) -> bool:
    tokens = tokenize(message)
    follow_up_tokens = {
        "them", "nua", "khac", "hon", "sau", "chi", "tiet", "tiep", "nhe", "day",
        "goi", "y", "loc", "bo", "sung", "it", "nhanh", "re", "cao", "thap",
    }
    return len(tokens) <= 6 or len(set(tokens) & follow_up_tokens) > 0


def _build_chat_context(message: str, history: List[ChatTurn], behavior_text: str) -> str:
    context_parts = [message.strip()]
    recent_user_turns = [turn.content for turn in history if turn.role == "user"][-2:]
    if recent_user_turns and _is_follow_up_question(message):
        context_parts.extend(recent_user_turns)
    if behavior_text:
        context_parts.append(behavior_text)
    return " ".join(part for part in context_parts if part).strip()


def _infer_budget(message: str) -> Optional[float]:
    match = re.search(r"(\d{2,7})\s*(k|nghin|ngan|vnd|đ|d|v?)\b", message.lower())
    if not match:
        return None
    try:
        value = float(match.group(1))
    except (TypeError, ValueError):
        return None
    unit = match.group(2)
    if unit in {"k", "nghin", "ngan"}:
        return value * 1000.0
    return value


def _format_budget_hint(price: object, budget: Optional[float]) -> str:
    if budget is None or not isinstance(price, (int, float)):
        return ""
    if float(price) <= budget:
        return f", nam trong ngan sach {budget:,.0f}"
    return f", cao hon ngan sach {budget:,.0f}"


def _detect_learning_style(message: str, history: List[ChatTurn]) -> Dict[str, float]:
    """Detect user's learning/reading style preferences."""
    style_scores = {
        "practical": 0.0,
        "theoretical": 0.0,
        "beginner": 0.0,
        "advanced": 0.0,
        "quick_read": 0.0,
        "deep_dive": 0.0,
        "entertaining": 0.0,
        "serious": 0.0,
    }
    
    msg_lower = message.lower()
    all_text = msg_lower
    for turn in history[-3:]:
        if turn.role == "user":
            all_text += " " + turn.content.lower()
    
    # Practical vs Theoretical
    if any(w in all_text for w in ["thuc hành", "apply", "dung", "project", "lam", "viet"]):
        style_scores["practical"] += 2.0
    if any(w in all_text for w in ["ly thuyet", "concept", "fundamental", "co so"]):
        style_scores["theoretical"] += 2.0
    
    # Beginner vs Advanced
    if any(w in all_text for w in ["co ban", "moi bat dau", "beginner", "from scratch"]):
        style_scores["beginner"] += 2.0
    if any(w in all_text for w in ["nang cao", "advanced", "expert", "deep"]):
        style_scores["advanced"] += 2.0
    
    # Quick vs Deep
    if any(w in all_text for w in ["nhanh", "short", "summary", "tong", "ngan"]):
        style_scores["quick_read"] += 2.0
    if any(w in all_text for w in ["chi tiet", "comprehensive", "complete", "day du"]):
        style_scores["deep_dive"] += 2.0
    
    # Entertaining vs Serious
    if any(w in all_text for w in ["giai tri", "fun", "story", "tieu thuyet", "truyen"]):
        style_scores["entertaining"] += 2.0
    if any(w in all_text for w in ["kinh doanh", "serious", "professional", "work"]):
        style_scores["serious"] += 2.0
    
    return style_scores


def _summarize_intent(message: str, history: List[ChatTurn]) -> str:
    budget = _infer_budget(message)
    tokens = _extract_focus_tokens(message)
    categories = {
        "python": "Python / lap trinh",
        "ai": "AI / machine learning",
        "data": "Data / SQL",
        "kinh": "Kinh doanh / tai chinh",
        "tam": "Tam ly / phat trien ban than",
        "truyen": "Van hoc / tieu thuyet",
        "mystery": "Trinh tham / bi an",
    }
    topic = next((label for token, label in categories.items() if token in tokens), None)
    intent_bits = []
    if topic:
        intent_bits.append(topic)
    if budget is not None:
        intent_bits.append(f"ngan sach {budget:,.0f}")
    if _is_follow_up_question(message) and any(turn.role == "user" for turn in history):
        intent_bits.append("cau hoi tiep theo co su dung ngu canh truoc do")
    return ", ".join(intent_bits)


def rerank_retrieved_products(
    message: str,
    retrieved: List[dict],
    top_k: int,
    view_counts: Dict[int, float] = None,
    purchase_counts: Dict[int, float] = None,
    history: List[ChatTurn] = None,
) -> List[dict]:
    query_tokens = _extract_focus_tokens(message)
    reranked: List[dict] = []
    view_counts = view_counts or {}
    purchase_counts = purchase_counts or {}
    history = history or []

    tech_intent_tokens = {
        "python", "ai", "ml", "machine", "learning", "code", "coding", "lap", "trinh", "data", "sql", "tensorflow",
        "pytorch", "devops", "backend", "frontend",
    }
    has_tech_intent = len(query_tokens & tech_intent_tokens) > 0
    
    # Detect user's learning style to apply contextual adjustments
    style_scores = _detect_learning_style(message, history)
    prefers_practical = style_scores["practical"] > style_scores["theoretical"]
    prefers_quick = style_scores["quick_read"] > style_scores["deep_dive"]

    for item in retrieved:
        dense_score = float(item.get("score", 0.0))
        lexical_score = _keyword_overlap_score(query_tokens, item)

        item_tokens = _product_tokens(item)

        final_score = (0.65 * dense_score) + (0.35 * lexical_score)

        # If user asks for technical topics, penalize items without any topic overlap.
        if has_tech_intent and not (item_tokens & tech_intent_tokens):
            final_score *= 0.35

        # Small boost for exact keyword match in title/category/description.
        if query_tokens and (item_tokens & query_tokens):
            final_score += 0.08
        
        # Behavior-aware boost: if user has shown interest in similar books before
        book_id = item.get("book_id")
        if book_id and isinstance(book_id, (int, str)):
            try:
                bid = int(book_id)
                if bid in purchase_counts and purchase_counts[bid] > 0:
                    final_score *= 1.15  # Stronger boost for purchased books
                elif bid in view_counts and view_counts[bid] > 0:
                    final_score *= 1.08  # Modest boost for viewed books
            except (TypeError, ValueError):
                pass
        
        # Learning style adjustment: prefer practical if user shows that preference
        if prefers_practical:
            title_lower = str(item.get("title", "")).lower()
            desc_lower = str(item.get("description", "")).lower()
            if any(w in title_lower + desc_lower for w in ["project", "thuc hanh", "example", "apply"]):
                final_score *= 1.12
        
        # Learning style adjustment: prefer shorter books if user wants quick reads
        if prefers_quick:
            title_lower = str(item.get("title", "")).lower()
            if any(w in title_lower for w in ["essentials", "quick", "guide", "summary"]):
                final_score *= 1.10

        row = dict(item)
        row["vector_score"] = round(dense_score, 4)
        row["lexical_score"] = round(lexical_score, 4)
        row["score"] = round(final_score, 4)
        reranked.append(row)

    reranked.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return reranked[: max(1, min(top_k, 10))]


def generate_personalized_answer(message: str, products: List[dict]) -> str:
    if not products:
        return "Minh chua tim du du lieu de goi y ca nhan hoa. Ban co the xem them mot vai sach de he thong hoc so thich."

    picks = []
    for product in products[:3]:
        title = str(product.get("title") or f"Book {product.get('book_id')}")
        category = str(product.get("category") or "general")
        score = float(product.get("score", 0.0))
        picks.append(f"{title} ({category}, similarity={score:.2f})")

    joined = "; ".join(picks)
    return (
        f"Dua tren hanh vi cua ban va cau hoi '{message}', minh de xuat: {joined}. "
        "Neu ban muon, minh co the goi y theo muc gia hoac theo the loai cu the hon."
    )


def _generate_smart_followups(message: str, products: List[dict], history: List[ChatTurn]) -> str:
    """Generate contextual follow-up suggestions based on retrieved books and history."""
    if not products:
        return ""
    
    suggestions = []
    budget = _infer_budget(message)
    has_previous_budget = any("ngan sach" in turn.content for turn in history if turn.role == "assistant")
    
    # Suggest price refinement if no budget was specified
    if not budget and not has_previous_budget and products:
        avg_price = sum(float(p.get("price", 0)) for p in products[:3]) / 3 if products else 0
        if avg_price > 0:
            lower = max(50000, int(avg_price * 0.7))
            upper = int(avg_price * 1.3)
            suggestions.append(f"Loc theo ngan sach ({lower:,}đ - {upper:,}đ)")
    
    # Suggest difficulty level refinement
    all_text = message.lower()
    if "co ban" not in all_text and "co so" not in all_text and "nang cao" not in all_text:
        suggestions.append("Chon muc do kho (co ban, trung tinh, hay nang cao)")
    
    # Suggest related categories
    tokens = _extract_focus_tokens(message)
    if "python" in tokens:
        suggestions.append("Them: sach ve web development hoac data science")
    elif "ai" in tokens or "ml" in tokens:
        suggestions.append("Them: sach ve Python hoac Statistics")
    elif "kinh" in tokens:
        suggestions.append("Them: sach ve tai chinh ca nhan hoac marketing")
    
    if suggestions:
        return "\nGoi y tiep theo: " + " | ".join(suggestions[:2])
    return ""


def generate_rag_advisory_answer(message: str, products: List[dict], history: Optional[List[ChatTurn]] = None) -> str:
    history = history or []
    if not products:
        follow_up_hint = ""
        if history:
            follow_up_hint = " Ban co the noi ro hon the loai, muc gia hoac muc do kho ban can."
        return (
            f"Voi cau hoi '{message}', minh chua tim thay sach phu hop trong Knowledge Base hien tai. "
            "Ban thu doi tu khoa cu the hon (vi du: python co ban, clean code, machine learning) hoac them sach dung chu de."
            + follow_up_hint
        )

    advice_lines: List[str] = []
    budget = _infer_budget(message)
    style_scores = _detect_learning_style(message, history)
    
    for idx, product in enumerate(products[:3], start=1):
        title = str(product.get("title") or f"Book {product.get('book_id')}")
        category = str(product.get("category") or "general")
        author = str(product.get("author") or "Unknown")
        score = float(product.get("score", 0.0))
        price = product.get("price")

        price_text = ""
        if isinstance(price, (int, float)):
            price_text = f", gia tham khao {float(price):.2f}{_format_budget_hint(price, budget)}"
        
        # Add personalized reason why this book matches
        reason = ""
        if style_scores["practical"] > style_scores["theoretical"]:
            reason = " [sach thuc hanh]"
        elif style_scores["beginner"] > style_scores["advanced"]:
            reason = " [phu hop co ban]"
        elif style_scores["quick_read"] > style_scores["deep_dive"]:
            reason = " [doc nhanh]"

        advice_lines.append(
            f"{idx}. {title} - {author} ({category}{price_text}){reason}"
        )

    top_score = float(products[0].get("score", 0.0)) if products else 0.0
    top_lexical = float(products[0].get("lexical_score", 0.0)) if products else 0.0
    if top_score < 0.08 and top_lexical <= 0.0:
        return (
            f"Voi cau hoi '{message}', minh chua tim thay ket qua that su sat nghia trong Knowledge Base hien tai. "
            "Ban co the noi ro hon chu de (vi du: python co ban, machine learning, clean code), hoac dong bo them du lieu sach lien quan."
        )

    next_step = "Ban muon minh loc tiep theo muc gia, muc do de, hay theo mot chu de cu the khong?"
    if history:
        next_step = "Neu ban muon, minh co the tiep tuc thu hep theo muc gia, muc do kho, hoac goi y them 3 quyen khac cung chu de."
    
    smart_followups = _generate_smart_followups(message, products, history)

    return (
        f"Tu cau hoi '{message}', minh da retrieve va rerank du lieu tu Knowledge Base. "
        "De xuat tu van cho ban:\n"
        + "\n".join(advice_lines)
        + "\n" + next_step
        + smart_followups
    )


def _safe_json_list(raw: Optional[str]) -> List[int]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [int(v) for v in parsed if isinstance(v, (int, float, str)) and str(v).isdigit()]
    except (ValueError, TypeError):
        pass
    return []


def _safe_json_count_map(raw: Optional[str]) -> Dict[int, float]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return {}
        out: Dict[int, float] = {}
        for key, val in parsed.items():
            try:
                bid = int(key)
                out[bid] = float(val)
            except (TypeError, ValueError):
                continue
        return out
    except (ValueError, TypeError):
        return {}


def _dump_count_map(data: Dict[int, float]) -> str:
    return json.dumps({str(k): float(v) for k, v in data.items() if v > 0})


def _normalize_recent_history(viewed_ids: List[int], max_size: int = 200) -> List[int]:
    deduped = list(dict.fromkeys(viewed_ids))
    return deduped[-max_size:]


def _build_text_from_book(book: dict) -> str:
    return " ".join(
        [
            str(book.get("title") or ""),
            str(book.get("author") or ""),
            str(book.get("description") or ""),
            str(book.get("category") or ""),
        ]
    )


def fetch_books() -> List[dict]:
    try:
        with urllib.request.urlopen(f"{BOOK_SERVICE_URL}/api/books/", timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
                return data["results"]
            if isinstance(data, list):
                return data
    except (urllib.error.URLError, ValueError, json.JSONDecodeError):
        pass
    return BOOK_POOL


def _extract_book_ids_from_order(order: dict) -> List[int]:
    items = order.get("items")
    if not isinstance(items, list):
        return []

    out: List[int] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("book_id")
        try:
            out.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    return out


def fetch_customer_order_book_ids(customer_id: int) -> List[int]:
    try:
        with urllib.request.urlopen(f"{ORDER_SERVICE_URL}/api/orders?customer_id={customer_id}", timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))
            if not isinstance(data, list):
                return []

            ordered_ids: List[int] = []
            for order in data:
                if isinstance(order, dict):
                    ordered_ids.extend(_extract_book_ids_from_order(order))

            # Keep order but remove duplicates.
            return list(dict.fromkeys(ordered_ids))
    except (urllib.error.URLError, ValueError, json.JSONDecodeError):
        return []


def fetch_customer_purchase_counts(customer_id: int) -> Dict[int, float]:
    try:
        with urllib.request.urlopen(f"{ORDER_SERVICE_URL}/api/orders?customer_id={customer_id}", timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))
            if not isinstance(data, list):
                return {}

            counts: Dict[int, float] = defaultdict(float)
            for order in data:
                if not isinstance(order, dict):
                    continue
                items = order.get("items")
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    try:
                        bid = int(item.get("book_id"))
                    except (TypeError, ValueError):
                        continue
                    qty_raw = item.get("quantity", 1)
                    try:
                        qty = max(1.0, float(qty_raw))
                    except (TypeError, ValueError):
                        qty = 1.0
                    counts[bid] += qty
            return dict(counts)
    except (urllib.error.URLError, ValueError, json.JSONDecodeError):
        return {}


def fetch_all_orders() -> List[dict]:
    try:
        with urllib.request.urlopen(f"{ORDER_SERVICE_URL}/api/orders", timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, list):
                return [o for o in data if isinstance(o, dict)]
    except (urllib.error.URLError, ValueError, json.JSONDecodeError):
        pass
    return []


def build_collaborative_signals(all_orders: List[dict]) -> tuple[Dict[tuple[int, int], float], Dict[int, float]]:
    pair_score: Dict[tuple[int, int], float] = defaultdict(float)
    popularity: Dict[int, float] = defaultdict(float)

    for order in all_orders:
        book_ids = _extract_book_ids_from_order(order)
        unique_ids = sorted(set(book_ids))
        if not unique_ids:
            continue

        for bid in unique_ids:
            popularity[bid] += 1.0

        for a, b in combinations(unique_ids, 2):
            pair_score[(a, b)] += 1.0
            pair_score[(b, a)] += 1.0

    return dict(pair_score), dict(popularity)


def _parse_order_datetime(raw_value: object) -> Optional[datetime]:
    if not raw_value:
        return None
    if isinstance(raw_value, datetime):
        dt = raw_value
    else:
        value = str(raw_value).strip()
        if not value:
            return None
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def build_temporal_covisitation_signals(
    all_orders: List[dict],
    recency_half_life_days: float = 30.0,
) -> Dict[tuple[int, int], float]:
    """Build co-visitation weights with time decay to prioritize recent behavior."""
    pair_score: Dict[tuple[int, int], float] = defaultdict(float)
    now = datetime.utcnow()
    safe_half_life = max(recency_half_life_days, 1.0)

    customer_orders: Dict[int, List[tuple[Optional[datetime], set[int]]]] = defaultdict(list)

    for order in all_orders:
        book_ids = sorted(set(_extract_book_ids_from_order(order)))
        if len(book_ids) < 1:
            continue

        created_at = _parse_order_datetime(order.get("created_at") or order.get("createdAt"))
        if created_at is None:
            decay = 0.8
        else:
            age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
            decay = math.exp(-math.log(2.0) * (age_days / safe_half_life))

        # Strong signal: items bought together in the same order.
        if len(book_ids) >= 2:
            for a, b in combinations(book_ids, 2):
                w = 1.25 * decay
                pair_score[(a, b)] += w
                pair_score[(b, a)] += w

        try:
            customer_id = int(order.get("customer_id"))
        except (TypeError, ValueError):
            customer_id = None
        if customer_id is not None:
            customer_orders[customer_id].append((created_at, set(book_ids)))

    # Cross-order continuation signal: items likely to be consumed in sequence.
    for _, rows in customer_orders.items():
        rows.sort(key=lambda x: x[0] or datetime.min)
        for idx in range(1, len(rows)):
            prev_dt, prev_items = rows[idx - 1]
            curr_dt, curr_items = rows[idx]
            if not prev_items or not curr_items:
                continue
            if curr_dt is None or prev_dt is None:
                seq_decay = 0.65
            else:
                gap_days = max(0.0, (curr_dt - prev_dt).total_seconds() / 86400.0)
                seq_decay = math.exp(-math.log(2.0) * (gap_days / (safe_half_life * 0.8)))

            w = 0.70 * seq_decay
            for a in prev_items:
                for b in curr_items:
                    if a == b:
                        continue
                    pair_score[(a, b)] += w
                    pair_score[(b, a)] += (0.40 * w)

    return dict(pair_score)


def collaborative_score(candidate_id: int, seen: set[int], pair_score: Dict[tuple[int, int], float]) -> float:
    if not seen:
        return 0.0
    total = 0.0
    for sid in seen:
        total += pair_score.get((sid, candidate_id), 0.0)
    return total / len(seen)


def novelty_score(candidate_id: int, popularity: Dict[int, float], max_popularity: float) -> float:
    if max_popularity <= 0:
        return 0.0
    pop = max(0.0, popularity.get(candidate_id, 0.0))
    # 1.0 means less popular (more novel), 0.0 means most popular.
    return max(0.0, 1.0 - (math.log1p(pop) / math.log1p(max_popularity)))


def select_diverse_recommendations(
    candidates: List[Recommendation],
    vectors: Dict[int, Dict[str, float]],
    top_k: int = 5,
    score_weight: float = 0.82,
) -> List[Recommendation]:
    if len(candidates) <= top_k:
        return candidates

    remaining = list(candidates)
    selected: List[Recommendation] = []
    safe_score_weight = min(0.95, max(0.55, score_weight))

    while remaining and len(selected) < top_k:
        best_idx = 0
        best_mmr = float("-inf")
        for idx, cand in enumerate(remaining):
            cand_vec = vectors.get(cand.book_id, {})
            if not selected or not cand_vec:
                diversity_penalty = 0.0
            else:
                diversity_penalty = max(
                    max(0.0, cosine_similarity_sparse(cand_vec, vectors.get(chosen.book_id, {})))
                    for chosen in selected
                )

            mmr = (safe_score_weight * float(cand.score)) - ((1.0 - safe_score_weight) * diversity_penalty)
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx

        selected.append(remaining.pop(best_idx))

    return selected


SERIES_STOPWORDS = {
    "tap", "tome", "vol", "volume", "chuong", "chapter", "phan", "part",
    "book", "edition", "the", "a", "an", "of", "va", "and", "to", "den",
}

RELATED_FRANCHISES = {
    "naruto": {"boruto"},
    "boruto": {"naruto"},
    "dragon ball": {"dragon ball super"},
    "dragon ball super": {"dragon ball"},
    "the fellowship of the ring": {"the two towers", "the return of the king", "the hobbit"},
    "the two towers": {"the fellowship of the ring", "the return of the king", "the hobbit"},
    "the return of the king": {"the fellowship of the ring", "the two towers", "the hobbit"},
    "the hobbit": {"the fellowship of the ring", "the two towers", "the return of the king"},
}


def _book_id_from_dict(book: dict) -> Optional[int]:
    raw_id = book.get("id", book.get("book_id"))
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def _extract_series_terms(book: dict) -> set[str]:
    title = str(book.get("title") or "")
    description = str(book.get("description") or "")

    title_tokens = tokenize(title)
    text_tokens = tokenize(f"{title} {description}")
    cleaned_title = [t for t in title_tokens if t not in SERIES_STOPWORDS and not t.isdigit()]
    cleaned_text = [t for t in text_tokens if t not in SERIES_STOPWORDS and not t.isdigit()]

    terms: set[str] = set()
    if cleaned_title:
        terms.add(cleaned_title[0])
    if len(cleaned_title) >= 2:
        terms.add(f"{cleaned_title[0]} {cleaned_title[1]}")

    for tok in cleaned_text:
        if len(tok) >= 4:
            terms.add(tok)

    return terms


def _extract_franchise_key(book: dict) -> str:
    title = str(book.get("title") or "")
    title_tokens = tokenize(title)
    if not title_tokens:
        return ""

    parts: List[str] = []
    for tok in title_tokens:
        if tok in {"tap", "vol", "volume", "part", "phan", "chapter", "chuong"}:
            break
        if tok.isdigit():
            break
        if tok in SERIES_STOPWORDS:
            continue
        parts.append(tok)
        if len(parts) >= 4:
            break

    if not parts:
        return ""
    return " ".join(parts)


def _primary_franchise_key(franchise_profile: Dict[str, float]) -> str:
    if not franchise_profile:
        return ""
    return max(franchise_profile.items(), key=lambda item: item[1])[0]


def build_series_profile(anchor_weights: Dict[int, float], book_by_id: Dict[int, dict]) -> Dict[str, float]:
    profile: Dict[str, float] = defaultdict(float)
    for bid, weight in anchor_weights.items():
        book = book_by_id.get(bid)
        if not book:
            continue
        terms = _extract_series_terms(book)
        if not terms:
            continue
        for term in terms:
            # Title-leading terms are extracted first; keep strong weights for franchise matching.
            profile[term] += float(weight)

    if not profile:
        return {}

    top_terms = sorted(profile.items(), key=lambda x: x[1], reverse=True)[:40]
    total = sum(v for _, v in top_terms)
    if total <= 0:
        return {}
    return {k: (v / total) for k, v in top_terms}


def build_franchise_profile(anchor_weights: Dict[int, float], book_by_id: Dict[int, dict]) -> Dict[str, float]:
    profile: Dict[str, float] = defaultdict(float)
    for bid, weight in anchor_weights.items():
        book = book_by_id.get(bid)
        if not book:
            continue
        franchise = _extract_franchise_key(book)
        if not franchise:
            continue
        profile[franchise] += float(weight)

    if not profile:
        return {}

    total = sum(profile.values())
    if total <= 0:
        return {}
    return {k: (v / total) for k, v in profile.items()}


def franchise_related_score(candidate_book: dict, franchise_profile: Dict[str, float]) -> float:
    if not franchise_profile:
        return 0.0
    candidate_franchise = _extract_franchise_key(candidate_book)
    if not candidate_franchise:
        return 0.0

    direct = franchise_profile.get(candidate_franchise, 0.0)
    if direct > 0:
        return min(1.0, direct * 3.0)

    related = 0.0
    for base, weight in franchise_profile.items():
        if candidate_franchise in RELATED_FRANCHISES.get(base, set()):
            related = max(related, weight * 0.65)
    return min(1.0, related * 2.0)


def strict_franchise_match(candidate_book: dict, primary_franchise: str) -> bool:
    if not primary_franchise:
        return True
    candidate_franchise = _extract_franchise_key(candidate_book)
    return candidate_franchise == primary_franchise


def _safe_price(book: dict) -> Optional[float]:
    raw = book.get("price")
    try:
        value = float(raw)
        if value > 0:
            return value
    except (TypeError, ValueError):
        return None
    return None


def build_user_intent_profile(
    book_by_id: Dict[int, dict],
    view_counts: Dict[int, float],
    purchase_counts: Dict[int, float],
    merged_history: List[int],
    recent_viewed_book_ids: Optional[List[int]] = None,
    explore_mode: bool = False,
) -> Dict[str, object]:
    author_w: Dict[str, float] = defaultdict(float)
    category_w: Dict[str, float] = defaultdict(float)
    franchise_w: Dict[str, float] = defaultdict(float)
    recent_author_w: Dict[str, float] = defaultdict(float)
    recent_category_w: Dict[str, float] = defaultdict(float)
    recent_franchise_w: Dict[str, float] = defaultdict(float)
    weighted_price_sum = 0.0
    total_weight = 0.0

    # Base behavior weights.
    book_weights: Dict[int, float] = defaultdict(float)
    for bid, cnt in view_counts.items():
        book_weights[bid] += (1.0 * float(cnt))
    for bid, cnt in purchase_counts.items():
        book_weights[bid] += (2.0 * float(cnt))

    # Recency emphasis: recent items should strongly steer next recommendations.
    recency_items = list(dict.fromkeys(merged_history))[-20:]
    for rank, bid in enumerate(recency_items):
        recency_boost = max(0.55, 2.8 - (0.12 * rank)) if explore_mode else max(0.35, 2.2 - (0.10 * rank))
        book_weights[bid] += recency_boost

        book = book_by_id.get(bid)
        if not book:
            continue
        author = str(book.get("author") or "").strip().lower()
        category = str(book.get("category") or "").strip().lower()
        franchise = _extract_franchise_key(book)

        recent_strength = max(0.5, 1.9 - (0.08 * rank))
        if author:
            recent_author_w[author] += recent_strength
        if category:
            recent_category_w[category] += recent_strength
        if franchise:
            recent_franchise_w[franchise] += recent_strength

    if recent_viewed_book_ids:
        recent_focus_items = list(dict.fromkeys(recent_viewed_book_ids))[-12:]
        for rank, bid in enumerate(recent_focus_items):
            focus_boost = max(0.8, 3.0 - (0.15 * rank)) if explore_mode else max(0.55, 1.8 - (0.08 * rank))
            book_weights[bid] += focus_boost

            book = book_by_id.get(bid)
            if not book:
                continue

            author = str(book.get("author") or "").strip().lower()
            category = str(book.get("category") or "").strip().lower()
            franchise = _extract_franchise_key(book)
            focus_strength = max(0.65, 2.1 - (0.10 * rank)) if explore_mode else max(0.45, 1.2 - (0.06 * rank))
            if author:
                recent_author_w[author] += focus_strength
            if category:
                recent_category_w[category] += focus_strength
            if franchise:
                recent_franchise_w[franchise] += focus_strength

    for bid, weight in book_weights.items():
        book = book_by_id.get(bid)
        if not book or weight <= 0:
            continue

        author = str(book.get("author") or "").strip().lower()
        category = str(book.get("category") or "").strip().lower()
        franchise = _extract_franchise_key(book)

        if author:
            author_w[author] += weight
        if category:
            category_w[category] += weight
        if franchise:
            franchise_w[franchise] += weight

        price = _safe_price(book)
        if price is not None:
            weighted_price_sum += price * weight
            total_weight += weight

    def _normalize_map(data: Dict[str, float], top_k: int = 12) -> Dict[str, float]:
        if not data:
            return {}
        ranked = sorted(data.items(), key=lambda x: x[1], reverse=True)[:top_k]
        total = sum(v for _, v in ranked)
        if total <= 0:
            return {}
        return {k: (v / total) for k, v in ranked}

    target_price = (weighted_price_sum / total_weight) if total_weight > 0 else None
    return {
        "authors": _normalize_map(author_w),
        "categories": _normalize_map(category_w),
        "franchises": _normalize_map(franchise_w),
        "recent_authors": _normalize_map(recent_author_w),
        "recent_categories": _normalize_map(recent_category_w),
        "recent_franchises": _normalize_map(recent_franchise_w),
        "recent_diversity": len(recent_author_w) + len(recent_category_w) + len(recent_franchise_w),
        "target_price": target_price,
    }


def candidate_intent_score(
    candidate_book: dict,
    intent_profile: Dict[str, object],
    broad_interest_mode: bool = False,
) -> float:
    if not intent_profile:
        return 0.0

    authors = intent_profile.get("authors") or {}
    categories = intent_profile.get("categories") or {}
    franchises = intent_profile.get("franchises") or {}
    recent_authors = intent_profile.get("recent_authors") or {}
    recent_categories = intent_profile.get("recent_categories") or {}
    recent_franchises = intent_profile.get("recent_franchises") or {}
    target_price = intent_profile.get("target_price")

    author = str(candidate_book.get("author") or "").strip().lower()
    category = str(candidate_book.get("category") or "").strip().lower()
    franchise = _extract_franchise_key(candidate_book)

    author_score = float(authors.get(author, 0.0)) if author else 0.0
    category_score = float(categories.get(category, 0.0)) if category else 0.0
    franchise_score = float(franchises.get(franchise, 0.0)) if franchise else 0.0
    recent_author_score = float(recent_authors.get(author, 0.0)) if author else 0.0
    recent_category_score = float(recent_categories.get(category, 0.0)) if category else 0.0
    recent_franchise_score = float(recent_franchises.get(franchise, 0.0)) if franchise else 0.0

    price_score = 0.0
    price = _safe_price(candidate_book)
    if target_price and price:
        # Relative distance score in [0,1].
        rel_gap = abs(price - float(target_price)) / max(float(target_price), 1.0)
        price_score = max(0.0, 1.0 - min(rel_gap, 1.0))

    if broad_interest_mode:
        return min(
            1.0,
            (0.28 * recent_franchise_score)
            + (0.24 * recent_category_score)
            + (0.18 * recent_author_score)
            + (0.12 * franchise_score)
            + (0.10 * category_score)
            + (0.05 * author_score)
            + (0.03 * price_score),
        )

    return min(
        1.0,
        (0.42 * franchise_score)
        + (0.24 * author_score)
        + (0.19 * category_score)
        + (0.15 * price_score)
        + (0.10 * recent_franchise_score)
        + (0.08 * recent_author_score)
        + (0.07 * recent_category_score),
    )


def series_related_score(candidate_book: dict, series_profile: Dict[str, float]) -> float:
    if not series_profile:
        return 0.0

    candidate_terms = _extract_series_terms(candidate_book)
    if not candidate_terms:
        return 0.0

    matched = 0.0
    for term in candidate_terms:
        matched += series_profile.get(term, 0.0)

    # Amplify small matches slightly so same-franchise books are clearly preferred.
    return min(1.0, matched * 2.5)


def build_anchor_book_weights(
    seen: set[int],
    view_counts: Dict[int, float],
    purchase_counts: Dict[int, float],
    recent_viewed_book_ids: Optional[List[int]] = None,
    explore_mode: bool = False,
) -> Dict[int, float]:
    """Build weighted anchor books from user behavior for relation scoring."""
    anchors: Dict[int, float] = {}

    for bid, cnt in view_counts.items():
        anchors[bid] = anchors.get(bid, 0.0) + (1.0 * float(cnt))
    for bid, cnt in purchase_counts.items():
        purchase_weight = 1.6 if not explore_mode else 0.9
        anchors[bid] = anchors.get(bid, 0.0) + (purchase_weight * float(cnt))

    if recent_viewed_book_ids:
        for rank, bid in enumerate(list(dict.fromkeys(recent_viewed_book_ids))[-12:]):
            recent_weight = max(0.75, 2.4 - (0.14 * rank)) if explore_mode else max(0.5, 1.4 - (0.08 * rank))
            anchors[bid] = anchors.get(bid, 0.0) + recent_weight

    # Ensure history-only ids still contribute lightly even if explicit counts are missing.
    for bid in seen:
        anchors[bid] = max(anchors.get(bid, 0.0), 0.5)

    return {bid: weight for bid, weight in anchors.items() if weight > 0}


def related_history_score(
    candidate_id: int,
    vectors: Dict[int, Dict[str, float]],
    anchor_weights: Dict[int, float],
) -> Tuple[float, Optional[int]]:
    candidate_vec = vectors.get(candidate_id, {})
    if not candidate_vec or not anchor_weights:
        return 0.0, None

    total_weight = sum(anchor_weights.values())
    if total_weight <= 0:
        return 0.0, None

    weighted_sum = 0.0
    best_anchor_id: Optional[int] = None
    best_anchor_score = -1.0

    for anchor_id, weight in anchor_weights.items():
        anchor_vec = vectors.get(anchor_id)
        if not anchor_vec:
            continue
        sim = max(0.0, cosine_similarity_sparse(candidate_vec, anchor_vec))
        weighted_sum += sim * weight
        if sim > best_anchor_score:
            best_anchor_score = sim
            best_anchor_id = anchor_id

    return (weighted_sum / total_weight), best_anchor_id


def recent_view_similarity_score(
    candidate_id: int,
    recent_viewed_book_ids: List[int],
    vectors: Dict[int, Dict[str, float]],
) -> Tuple[float, Optional[int]]:
    if not recent_viewed_book_ids:
        return 0.0, None

    candidate_vec = vectors.get(candidate_id, {})
    if not candidate_vec:
        return 0.0, None

    total_weight = 0.0
    weighted_sum = 0.0
    best_anchor_id: Optional[int] = None
    best_anchor_score = -1.0

    recent_items = list(dict.fromkeys(recent_viewed_book_ids))[-12:]
    for rank, anchor_id in enumerate(recent_items):
        anchor_vec = vectors.get(anchor_id)
        if not anchor_vec:
            continue
        anchor_weight = max(0.4, 2.2 - (0.15 * rank))
        sim = max(0.0, cosine_similarity_sparse(candidate_vec, anchor_vec))
        weighted_sum += sim * anchor_weight
        total_weight += anchor_weight
        if sim > best_anchor_score:
            best_anchor_score = sim
            best_anchor_id = anchor_id

    if total_weight <= 0:
        return 0.0, None
    return (weighted_sum / total_weight), best_anchor_id


def build_tfidf_vectors(books: List[dict]) -> Dict[int, Dict[str, float]]:
    docs: Dict[int, List[str]] = {}
    doc_freq: Dict[str, int] = {}

    for book in books:
        book_id = book.get("id", book.get("book_id"))
        if book_id is None:
            continue
        try:
            bid = int(book_id)
        except (TypeError, ValueError):
            continue

        tokens = tokenize(_build_text_from_book(book))
        if not tokens:
            continue
        docs[bid] = tokens
        for term in set(tokens):
            doc_freq[term] = doc_freq.get(term, 0) + 1

    total_docs = max(len(docs), 1)
    vectors: Dict[int, Dict[str, float]] = {}

    for bid, tokens in docs.items():
        tf: Dict[str, float] = {}
        token_count = float(len(tokens))
        for term in tokens:
            tf[term] = tf.get(term, 0.0) + 1.0 / token_count

        vector: Dict[str, float] = {}
        for term, tf_val in tf.items():
            idf = math.log((1 + total_docs) / (1 + doc_freq.get(term, 0))) + 1.0
            vector[term] = tf_val * idf
        vectors[bid] = vector

    return vectors


def cosine_similarity_sparse(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    shared = set(a.keys()) & set(b.keys())
    dot = sum(a[t] * b[t] for t in shared)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_user_profile_vector(
    vectors: Dict[int, Dict[str, float]],
    view_counts: Dict[int, float],
    purchase_counts: Dict[int, float],
) -> Dict[str, float]:
    book_weights: Dict[int, float] = {}
    for bid, cnt in view_counts.items():
        if bid in vectors:
            book_weights[bid] = book_weights.get(bid, 0.0) + (1.0 * float(cnt))
    for bid, cnt in purchase_counts.items():
        if bid in vectors:
            book_weights[bid] = book_weights.get(bid, 0.0) + (1.8 * float(cnt))

    total_weight = sum(book_weights.values())
    if total_weight <= 0:
        return {}

    profile: Dict[str, float] = {}
    for bid, weight in book_weights.items():
        vec = vectors[bid]
        scale = weight / total_weight
        for term, weight in vec.items():
            profile[term] = profile.get(term, 0.0) + weight * scale
    return profile


def explain_reason(profile_vec: Dict[str, float], candidate_vec: Dict[str, float]) -> str:
    overlap = set(profile_vec.keys()) & set(candidate_vec.keys())
    if not overlap:
        return "Recommended by AI similarity model"
    top_terms = sorted(overlap, key=lambda t: profile_vec[t] * candidate_vec[t], reverse=True)[:3]
    return "Similar to your interests: " + ", ".join(top_terms)


def explain_hybrid_reason(content_score: float, collab_score: float, popularity_score: float, base_reason: str) -> str:
    if collab_score > content_score and collab_score > popularity_score and collab_score > 0:
        return "Users with similar purchases also bought this"
    if popularity_score > content_score and popularity_score > 0:
        return "Trending choice from customer orders"
    return base_reason


@app.post("/api/recommendations", response_model=List[Recommendation])
def get_recommendations(payload: RecommendRequest):
    db: Session = SessionLocal()
    merged_history: List[int] = list(payload.viewed_book_ids)
    try:
        profile = db.query(UserPreferenceRow).filter(UserPreferenceRow.customer_id == payload.customer_id).first()
        view_counts: Dict[int, float] = {}
        purchase_counts: Dict[int, float] = {}
        recent_viewed_book_ids = _normalize_recent_history(payload.recent_viewed_book_ids or payload.viewed_book_ids, max_size=20)
        explore_mode = bool(payload.explore_mode or recent_viewed_book_ids)

        if profile:
            if not explore_mode:
                historical = _safe_json_list(profile.viewed_book_ids)
                merged_history = list(dict.fromkeys(historical + payload.viewed_book_ids))
                view_counts = _safe_json_count_map(profile.viewed_book_counts)
                purchase_counts = _safe_json_count_map(profile.purchased_book_counts)
            else:
                historical = _safe_json_list(profile.viewed_book_ids)
                merged_history = list(dict.fromkeys(historical[-20:] + payload.viewed_book_ids))

                # Keep a damped long-term memory in explore mode so repeated events still matter.
                for bid, cnt in _safe_json_count_map(profile.viewed_book_counts).items():
                    view_counts[bid] = max(view_counts.get(bid, 0.0), 0.45 * float(cnt))
                for bid, cnt in _safe_json_count_map(profile.purchased_book_counts).items():
                    purchase_counts[bid] = max(purchase_counts.get(bid, 0.0), 0.25 * float(cnt))

        for bid in payload.viewed_book_ids:
            view_counts[bid] = view_counts.get(bid, 0.0) + 1.0

        books = fetch_books()
        book_by_id: Dict[int, dict] = {}
        for book in books:
            bid = _book_id_from_dict(book)
            if bid is not None:
                book_by_id[bid] = book

        focus_categories: set[str] = set()
        focus_franchises: set[str] = set()
        focus_authors: set[str] = set()
        focus_ids = recent_viewed_book_ids or payload.viewed_book_ids
        for bid in focus_ids:
            book = book_by_id.get(bid)
            if not book:
                continue
            category = str(book.get("category") or "").strip().lower()
            franchise = _extract_franchise_key(book)
            author = str(book.get("author") or "").strip().lower()
            if category:
                focus_categories.add(category)
            if franchise:
                focus_franchises.add(franchise)
            if author:
                focus_authors.add(author)

        def _explore_purchase_alignment_weight(book_id: int) -> float:
            if not explore_mode:
                return 1.0
            book = book_by_id.get(book_id)
            if not book:
                return 0.20
            category = str(book.get("category") or "").strip().lower()
            franchise = _extract_franchise_key(book)
            author = str(book.get("author") or "").strip().lower()
            if franchise and franchise in focus_franchises:
                return 1.00
            if category and category in focus_categories:
                return 0.85
            if author and author in focus_authors:
                return 0.72
            return 0.15

        purchase_payload_weight = 0.65 if explore_mode else 1.0
        for bid in payload.purchased_book_ids:
            alignment_weight = _explore_purchase_alignment_weight(bid)
            purchase_counts[bid] = purchase_counts.get(bid, 0.0) + (purchase_payload_weight * alignment_weight)

        vectors = build_tfidf_vectors(books)
        purchased_ids: List[int] = []
        purchased_ids = list(dict.fromkeys(payload.purchased_book_ids + fetch_customer_order_book_ids(payload.customer_id)))
        purchase_counts_remote = fetch_customer_purchase_counts(payload.customer_id)
        remote_weight = 0.45 if explore_mode else 1.0
        for bid, cnt in purchase_counts_remote.items():
            if explore_mode:
                alignment_weight = _explore_purchase_alignment_weight(bid)
                purchase_counts[bid] = purchase_counts.get(bid, 0.0) + (remote_weight * alignment_weight * float(cnt))
            else:
                purchase_counts[bid] = max(purchase_counts.get(bid, 0.0), remote_weight * float(cnt))
        if not explore_mode:
            merged_history = list(dict.fromkeys(merged_history + purchased_ids))

        merged_history = _normalize_recent_history(merged_history)
        seen = set(merged_history)
        user_has_history = bool(seen or view_counts or purchase_counts)
        anchor_weights = build_anchor_book_weights(
            seen=seen,
            view_counts=view_counts,
            purchase_counts=purchase_counts,
            recent_viewed_book_ids=recent_viewed_book_ids,
            explore_mode=explore_mode,
        )
        series_profile = build_series_profile(anchor_weights=anchor_weights, book_by_id=book_by_id)
        franchise_profile = build_franchise_profile(anchor_weights=anchor_weights, book_by_id=book_by_id)
        primary_franchise = _primary_franchise_key(franchise_profile)
        intent_profile = build_user_intent_profile(
            book_by_id=book_by_id,
            view_counts=view_counts,
            purchase_counts=purchase_counts,
            merged_history=merged_history,
            recent_viewed_book_ids=recent_viewed_book_ids,
            explore_mode=explore_mode,
        )
        broad_interest_mode = int(intent_profile.get("recent_diversity") or 0) >= 4
        has_series_profile = bool(series_profile)
        has_franchise_profile = bool(franchise_profile)
        has_behavior_history = bool(anchor_weights)
        profile_vec = build_user_profile_vector(
            vectors=vectors,
            view_counts=view_counts,
            purchase_counts=purchase_counts,
        )

        all_orders = fetch_all_orders()
        pair_score, popularity = build_collaborative_signals(all_orders)
        temporal_pair_score = build_temporal_covisitation_signals(all_orders)
        max_popularity = max(popularity.values()) if popularity else 0.0
        candidate_ids = []
        for book in books:
            raw_id = book.get("id", book.get("book_id"))
            try:
                candidate_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if candidate_id in seen:
                continue
            candidate_ids.append(candidate_id)

        deep_scores = _predict_deep_scores(
            customer_id=payload.customer_id,
            candidate_ids=candidate_ids,
            seen=seen,
            view_counts=view_counts,
            purchase_counts=purchase_counts,
            popularity=popularity,
            max_popularity=max_popularity,
        )

        candidates = []
        for book in books:
            raw_id = book.get("id", book.get("book_id"))
            try:
                candidate_id = int(raw_id)
            except (TypeError, ValueError):
                continue

            if candidate_id in seen:
                continue

            candidate_vec = vectors.get(candidate_id, {})
            content_score = cosine_similarity_sparse(profile_vec, candidate_vec)
            collab = collaborative_score(candidate_id, seen, pair_score)
            temporal_collab = collaborative_score(candidate_id, seen, temporal_pair_score)
            history_related_score, anchor_id = related_history_score(
                candidate_id=candidate_id,
                vectors=vectors,
                anchor_weights=anchor_weights,
            )
            recent_explore_score, recent_anchor_id = recent_view_similarity_score(
                candidate_id=candidate_id,
                recent_viewed_book_ids=recent_viewed_book_ids,
                vectors=vectors,
            )
            series_score = series_related_score(candidate_book=book, series_profile=series_profile)
            franchise_score = franchise_related_score(candidate_book=book, franchise_profile=franchise_profile)
            intent_score = candidate_intent_score(
                candidate_book=book,
                intent_profile=intent_profile,
                broad_interest_mode=broad_interest_mode,
            )
            popularity_boost = (popularity.get(candidate_id, 0.0) / max_popularity) if max_popularity > 0 else 0.0
            freshness = novelty_score(candidate_id, popularity=popularity, max_popularity=max_popularity)
            deep_score = deep_scores.get(candidate_id)

            if explore_mode and focus_categories:
                candidate_category = str(book.get("category") or "").strip().lower()
                category_match = candidate_category in focus_categories
                strict_single_category_focus = len(focus_categories) == 1
                if strict_single_category_focus:
                    if not category_match:
                        continue
                elif not category_match and recent_explore_score < 0.22 and intent_score < 0.24:
                    continue

            if payload.strict_franchise_only and primary_franchise:
                if not strict_franchise_match(candidate_book=book, primary_franchise=primary_franchise):
                    continue

            # Enforce minimum relation to viewed/purchased history when we have behavior data.
            relation_gate = max(
                content_score,
                collab,
                temporal_collab,
                history_related_score,
                recent_explore_score,
                series_score,
                franchise_score,
                intent_score,
            )
            if has_behavior_history and relation_gate < 0.01:
                continue

            # If we clearly detect series/franchise preference, filter out off-series noise.
            if explore_mode:
                pass
            elif has_behavior_history and not broad_interest_mode and has_series_profile and series_score < 0.10 and max(collab, temporal_collab) < 0.20 and history_related_score < 0.12:
                continue
            if has_behavior_history and not broad_interest_mode and has_franchise_profile and franchise_score < 0.18 and max(collab, temporal_collab) < 0.22 and history_related_score < 0.15:
                continue
            if has_behavior_history and intent_score < 0.05 and max(collab, temporal_collab) < 0.15 and history_related_score < 0.10 and franchise_score < 0.12:
                continue

            # Prefer trained deep model scores when available.
            if deep_score is not None:
                similarity = (
                    (0.34 * deep_score)
                    + (0.20 * series_score)
                    + (0.17 * franchise_score)
                    + (0.16 * intent_score)
                    + (0.12 * history_related_score)
                    + (0.10 * recent_explore_score)
                    + (0.08 * temporal_collab)
                    + (0.04 * collab)
                    + (0.03 * popularity_boost)
                    + (0.04 * freshness)
                )
                reason = "Related to books you viewed or purchased" if user_has_history else "Popular for similar readers"
            else:
                # Weighted hybrid score fallback.
                similarity = (
                    (0.22 * content_score)
                    + (0.24 * series_score)
                    + (0.22 * franchise_score)
                    + (0.18 * intent_score)
                    + (0.16 * history_related_score)
                    + (0.12 * recent_explore_score)
                    + (0.12 * temporal_collab)
                    + (0.07 * collab)
                    + (0.04 * popularity_boost)
                    + (0.05 * freshness)
                )
                reason = "Related to books you viewed or purchased" if user_has_history else "Popular for similar readers"

            if franchise_score >= 0.28 or series_score >= 0.22:
                similarity += 0.05
                reason = "Same series as books you viewed or purchased"
            elif intent_score >= 0.28:
                similarity += 0.03
                reason = "Matches your reading taste and behavior"
            if payload.strict_franchise_only and primary_franchise:
                reason = "Same franchise as books you viewed or purchased"
            if temporal_collab >= 0.25:
                similarity += 0.02
                reason = "Often bought/viewed together recently"
            if explore_mode and recent_explore_score >= 0.18:
                similarity += 0.06
                reason = "Related to books you viewed recently"
            if explore_mode and focus_categories:
                candidate_category = str(book.get("category") or "").strip().lower()
                if candidate_category in focus_categories:
                    similarity += 0.04
                    reason = "Same category as books you viewed recently"
            if anchor_id is not None and anchor_id in purchase_counts:
                similarity += 0.03
                reason = "Related to books you purchased"
            elif anchor_id is not None and anchor_id in view_counts:
                reason = "Related to books you viewed"
            elif recent_anchor_id is not None:
                reason = "Related to books you viewed recently"

            # Cold-start fallback: still produce useful ranking when user has no history.
            if not profile_vec and deep_score is None:
                if explore_mode and recent_explore_score > 0:
                    similarity = max(0.12, (0.80 * recent_explore_score) + (0.20 * freshness))
                    reason = "Related to books you viewed recently"
                else:
                    similarity = max(0.08, (0.75 * popularity_boost) + (0.25 * freshness))
                    reason = "Trending choice from customer orders"

            candidates.append(
                Recommendation(
                    book_id=candidate_id,
                    score=round(float(similarity), 4),
                    reason=reason,
                )
            )

        if explore_mode and len(candidates) < 5:
            explore_candidates = {item.book_id: item for item in candidates}
            for book in books:
                candidate_id = _book_id_from_dict(book)
                if candidate_id is None or candidate_id in seen or candidate_id in explore_candidates:
                    continue

                if focus_categories and len(focus_categories) == 1:
                    candidate_category = str(book.get("category") or "").strip().lower()
                    if candidate_category not in focus_categories:
                        continue

                candidate_vec = vectors.get(candidate_id, {})
                recent_explore_score, recent_anchor_id = recent_view_similarity_score(
                    candidate_id=candidate_id,
                    recent_viewed_book_ids=recent_viewed_book_ids,
                    vectors=vectors,
                )
                if recent_explore_score <= 0 and max_popularity <= 0:
                    continue

                freshness = novelty_score(candidate_id, popularity=popularity, max_popularity=max_popularity)
                popularity_boost = (popularity.get(candidate_id, 0.0) / max_popularity) if max_popularity > 0 else 0.0
                content_seed = 0.0
                if recent_anchor_id is not None:
                    content_seed = max(
                        0.0,
                        cosine_similarity_sparse(candidate_vec, vectors.get(recent_anchor_id, {})),
                    )
                similarity = (
                    (0.64 * recent_explore_score)
                    + (0.14 * content_seed)
                    + (0.12 * freshness)
                    + (0.10 * popularity_boost)
                )
                explore_candidates[candidate_id] = Recommendation(
                    book_id=candidate_id,
                    score=round(float(similarity), 4),
                    reason="Related to books you viewed recently",
                )

            if explore_candidates:
                candidates = list(explore_candidates.values())

        candidates.sort(key=lambda item: item.score, reverse=True)
        final_recommendations = select_diverse_recommendations(
            candidates=candidates,
            vectors=vectors,
            top_k=5,
            score_weight=0.82,
        )

        if not final_recommendations:
            fallback_candidates: List[Recommendation] = []
            for book in books:
                candidate_id = _book_id_from_dict(book)
                if candidate_id is None or candidate_id in seen:
                    continue
                pop = (popularity.get(candidate_id, 0.0) / max_popularity) if max_popularity > 0 else 0.0
                fresh = novelty_score(candidate_id, popularity=popularity, max_popularity=max_popularity)
                score = (0.70 * pop) + (0.30 * fresh)
                fallback_candidates.append(
                    Recommendation(
                        book_id=candidate_id,
                        score=round(float(score), 4),
                        reason="Trending choice from customer orders",
                    )
                )
            fallback_candidates.sort(key=lambda item: item.score, reverse=True)
            final_recommendations = select_diverse_recommendations(
                candidates=fallback_candidates,
                vectors=vectors,
                top_k=5,
                score_weight=0.86,
            )

        viewed_json = json.dumps(merged_history)
        now = datetime.utcnow()
        if profile:
            profile.viewed_book_ids = viewed_json
            profile.viewed_book_counts = _dump_count_map(view_counts)
            profile.purchased_book_counts = _dump_count_map(purchase_counts)
            profile.updated_at = now
        else:
            db.add(
                UserPreferenceRow(
                    customer_id=payload.customer_id,
                    viewed_book_ids=viewed_json,
                    viewed_book_counts=_dump_count_map(view_counts),
                    purchased_book_counts=_dump_count_map(purchase_counts),
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


@app.post("/api/recommendations/track-view")
def track_view(payload: TrackViewRequest):
    db: Session = SessionLocal()
    try:
        profile = db.query(UserPreferenceRow).filter(UserPreferenceRow.customer_id == payload.customer_id).first()
        now = datetime.utcnow()

        if profile:
            history = _safe_json_list(profile.viewed_book_ids)
            history.append(payload.book_id)
            normalized = _normalize_recent_history(history)

            view_counts = _safe_json_count_map(profile.viewed_book_counts)
            view_counts[payload.book_id] = view_counts.get(payload.book_id, 0.0) + 1.0

            profile.viewed_book_ids = json.dumps(normalized)
            profile.viewed_book_counts = _dump_count_map(view_counts)
            profile.updated_at = now
        else:
            db.add(
                UserPreferenceRow(
                    customer_id=payload.customer_id,
                    viewed_book_ids=json.dumps([payload.book_id]),
                    viewed_book_counts=_dump_count_map({payload.book_id: 1.0}),
                    purchased_book_counts=_dump_count_map({}),
                    updated_at=now,
                )
            )

        db.commit()
    finally:
        db.close()

    return {"ok": True}


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


@app.post("/api/ai/knowledge/sync")
def sync_knowledge_base(customer_id: int | None = None):
    db: Session = SessionLocal()
    try:
        books = fetch_books()
        model_source = sync_product_vectors(db, books)

        if customer_id is not None:
            profile = db.query(UserPreferenceRow).filter(UserPreferenceRow.customer_id == customer_id).first()
            viewed_ids = _safe_json_list(profile.viewed_book_ids) if profile else []
            view_counts = _safe_json_count_map(profile.viewed_book_counts) if profile else {}
            purchase_counts = _safe_json_count_map(profile.purchased_book_counts) if profile else {}
            behavior_text = build_behavior_text(customer_id, viewed_ids, view_counts, purchase_counts)
            user_vector, source = encode_text_embedding(behavior_text)
            model_source = source
            upsert_knowledge_vector(
                db=db,
                entity_type="user",
                entity_id=str(customer_id),
                vector=user_vector,
                metadata={"customer_id": customer_id, "history_size": len(viewed_ids)},
            )

        db.commit()
        product_count = db.query(KnowledgeVectorRow).filter(KnowledgeVectorRow.entity_type == "product").count()
        return {
            "ok": True,
            "model_source": model_source,
            "product_vectors": product_count,
            "customer_id": customer_id,
        }
    finally:
        db.close()


@app.post("/api/ai/chat", response_model=ChatResponse)
def ai_chat(payload: ChatRequest):
    db: Session = SessionLocal()
    try:
        books = fetch_books()
        model_source = sync_product_vectors(db, books)
        history = _normalize_chat_history(payload.history)

        profile = db.query(UserPreferenceRow).filter(UserPreferenceRow.customer_id == payload.customer_id).first()
        viewed_ids = _safe_json_list(profile.viewed_book_ids) if profile else []
        view_counts = _safe_json_count_map(profile.viewed_book_counts) if profile else {}
        purchase_counts = _safe_json_count_map(profile.purchased_book_counts) if profile else {}
        remote_purchase_counts = fetch_customer_purchase_counts(payload.customer_id)
        for bid, cnt in remote_purchase_counts.items():
            purchase_counts[bid] = max(purchase_counts.get(bid, 0.0), cnt)

        behavior_text = build_behavior_text(
            customer_id=payload.customer_id,
            viewed_ids=viewed_ids,
            view_counts=view_counts,
            purchase_counts=purchase_counts,
        )
        intent_hint = _summarize_intent(payload.message, history)
        query_text = _build_chat_context(payload.message, history, behavior_text)
        if intent_hint:
            query_text = f"{query_text} {intent_hint}".strip()
        user_vector, source = encode_text_embedding(query_text)
        model_source = source

        upsert_knowledge_vector(
            db=db,
            entity_type="user",
            entity_id=str(payload.customer_id),
            vector=user_vector,
            metadata={
                "customer_id": payload.customer_id,
                "query": payload.message,
                "history_size": len(viewed_ids),
            },
        )

        # Retrieval: fetch a wider candidate set from vector KB before reranking.
        retrieved_candidates = retrieve_top_products(db, user_vector=user_vector, top_k=max(10, payload.top_k * 3))
        retrieved_candidates = filter_retrieved_by_query_tokens(payload.message, retrieved_candidates)
        retrieved = rerank_retrieved_products(
            message=payload.message,
            retrieved=retrieved_candidates,
            top_k=payload.top_k,
            view_counts=view_counts,
            purchase_counts=purchase_counts,
            history=history,
        )
        answer = generate_rag_advisory_answer(payload.message, retrieved, history=history)
        db.commit()

        return ChatResponse(
            answer=answer,
            retrieved_products=retrieved,
            model_source=model_source,
            retrieval_count=len(retrieved),
        )
    finally:
        db.close()


@app.get("/api/recommendations/health")
def recommender_health():
    model_type = "transformer" if SentenceTransformer is not None else "hash-fallback"
    deep_model_ready = _load_deep_model() is not None
    return {
        "service": "recommender-ai-service",
        "status": "ok",
        "ai_mode": model_type,
        "embedding_model": EMBEDDING_MODEL_NAME,
        "deep_model_enabled": DEEP_MODEL_ENABLED,
        "deep_model_ready": deep_model_ready,
        "deep_model_dir": DEEP_MODEL_DIR,
        "deep_model_error": _deep_model_error,
    }
