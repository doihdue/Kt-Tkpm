import json
import importlib
import math
import os
import re
import threading
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, List, Optional
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

SentenceTransformer = None

app = FastAPI(title="Recommender AI Service")

DB_URL = os.getenv(
    "DB_URL",
    "mysql+pymysql://root:123456@db:3306/recommender_db",
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
    purchased_book_ids: List[int] = []


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


class ChatResponse(BaseModel):
    answer: str
    retrieved_products: List[dict]
    model_source: str


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


def collaborative_score(candidate_id: int, seen: set[int], pair_score: Dict[tuple[int, int], float]) -> float:
    if not seen:
        return 0.0
    total = 0.0
    for sid in seen:
        total += pair_score.get((sid, candidate_id), 0.0)
    return total / len(seen)


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
            book_weights[bid] = book_weights.get(bid, 0.0) + (2.5 * float(cnt))

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

        if profile:
            historical = _safe_json_list(profile.viewed_book_ids)
            merged_history = list(dict.fromkeys(historical + payload.viewed_book_ids))
            view_counts = _safe_json_count_map(profile.viewed_book_counts)
            purchase_counts = _safe_json_count_map(profile.purchased_book_counts)

        for bid in payload.viewed_book_ids:
            view_counts[bid] = view_counts.get(bid, 0.0) + 1.0
        for bid in payload.purchased_book_ids:
            purchase_counts[bid] = purchase_counts.get(bid, 0.0) + 1.0

        books = fetch_books()
        vectors = build_tfidf_vectors(books)
        purchased_ids = list(dict.fromkeys(payload.purchased_book_ids + fetch_customer_order_book_ids(payload.customer_id)))
        purchase_counts_remote = fetch_customer_purchase_counts(payload.customer_id)
        for bid, cnt in purchase_counts_remote.items():
            purchase_counts[bid] = max(purchase_counts.get(bid, 0.0), cnt)

        merged_history = list(dict.fromkeys(merged_history + purchased_ids))
        merged_history = _normalize_recent_history(merged_history)
        seen = set(merged_history)
        profile_vec = build_user_profile_vector(
            vectors=vectors,
            view_counts=view_counts,
            purchase_counts=purchase_counts,
        )

        all_orders = fetch_all_orders()
        pair_score, popularity = build_collaborative_signals(all_orders)
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
            popularity_boost = (popularity.get(candidate_id, 0.0) / max_popularity) if max_popularity > 0 else 0.0
            deep_score = deep_scores.get(candidate_id)

            # Prefer trained deep model scores when available.
            if deep_score is not None:
                similarity = (0.85 * deep_score) + (0.10 * collab) + (0.05 * popularity_boost)
                reason = "Recommended by trained deep learning model"
            else:
                # Weighted hybrid score fallback.
                similarity = (0.65 * content_score) + (0.25 * collab) + (0.10 * popularity_boost)
                reason = explain_hybrid_reason(
                    content_score=content_score,
                    collab_score=collab,
                    popularity_score=popularity_boost,
                    base_reason=explain_reason(profile_vec, candidate_vec),
                )

            # Cold-start fallback: still produce useful ranking when user has no history.
            if not profile_vec and deep_score is None:
                if max_popularity > 0:
                    similarity = max(0.1, 0.8 * popularity_boost + 0.2 * max(0.0, 1.0 - (candidate_id * 0.01)))
                else:
                    similarity = max(0.1, 1.0 - (candidate_id * 0.01))

            candidates.append(
                Recommendation(
                    book_id=candidate_id,
                    score=round(float(similarity), 4),
                    reason=reason,
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        final_recommendations = candidates[:5]

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
        query_text = f"{payload.message} {behavior_text}".strip()
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

        retrieved = retrieve_top_products(db, user_vector=user_vector, top_k=payload.top_k)
        answer = generate_personalized_answer(payload.message, retrieved)
        db.commit()

        return ChatResponse(
            answer=answer,
            retrieved_products=retrieved,
            model_source=model_source,
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
