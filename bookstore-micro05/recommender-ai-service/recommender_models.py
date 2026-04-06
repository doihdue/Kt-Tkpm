"""
SQLAlchemy ORM Models for Recommender AI Service
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, Text, LargeBinary, Index
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class RecommendationEventRow(Base):
    __tablename__ = "recommendation_events"

    id = Column(String(36), primary_key=True)
    customer_id = Column(Integer, nullable=False, index=True)
    viewed_book_ids = Column(Text, nullable=False)
    recommendations = Column(Text, nullable=False)
    model_version = Column(String(50), default='ncf-graph-v1')
    inference_time_ms = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class UserPreferenceRow(Base):
    __tablename__ = "recommender_user_preferences"

    customer_id = Column(Integer, primary_key=True)
    viewed_book_ids = Column(Text, nullable=False)
    viewed_book_counts = Column(Text, nullable=True)
    purchased_book_counts = Column(Text, nullable=True)
    user_embedding = Column(Text, nullable=True)
    preference_vector = Column(Text, nullable=True)
    total_spent = Column(Float, default=0.0)
    purchase_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)


class KnowledgeVectorRow(Base):
    __tablename__ = "recommender_knowledge_vectors"

    id = Column(String(128), primary_key=True)
    entity_type = Column(String(32), nullable=False, index=True)
    entity_id = Column(String(64), nullable=False, index=True)
    vector_json = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    embedding_model = Column(String(100))
    updated_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('idx_entity', 'entity_type', 'entity_id'),
    )


class RecommenderBook(Base):
    __tablename__ = "recommender_books"

    book_id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    author = Column(String(255))
    category = Column(String(100), index=True)
    price = Column(Float)
    rating = Column(Float)
    published_year = Column(Integer)
    pages = Column(Integer)
    language = Column(String(50))
    description = Column(Text)
    item_embedding = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ModelMetadata(Base):
    __tablename__ = "model_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String(100), nullable=False)
    model_version = Column(String(50))
    model_type = Column(String(100))
    training_samples = Column(Integer)
    num_users = Column(Integer)
    num_items = Column(Integer)
    embedding_dim = Column(Integer)
    train_loss = Column(Float)
    val_loss = Column(Float)
    auc_score = Column(Float)
    training_time_seconds = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


class InteractionHistory(Base):
    __tablename__ = "interaction_history"

    interaction_id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False, index=True)
    book_id = Column(Integer, nullable=False, index=True)
    event_type = Column(String(50))
    rating = Column(Float, nullable=True)
    timestamp = Column(DateTime, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
