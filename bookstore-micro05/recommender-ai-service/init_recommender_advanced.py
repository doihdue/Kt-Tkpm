"""
Advanced Initialization Script for Recommender AI Service
Generates large-scale dataset, trains deep learning model, and populates database
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import List, Dict

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Import generators and models
from dataset_generator import generate_books, generate_customer_behavior, save_dataset
from deep_learning_model import NCFGraphRecommenderModel

print("📦 Importing dependencies...")
try:
    import numpy as np
    print("✓ NumPy imported")
except ImportError:
    print("⚠️  NumPy not found, some features may be limited")

DB_URL = os.getenv(
    "DB_URL",
    "mysql+pymysql://root:123456@db:3306/recommender_db",
)

# Initialize database connection
engine = create_engine(DB_URL, pool_pre_ping=True)


def ensure_database_exists(db_url: str):
    """Create database if it doesn't exist"""
    print("\n🗄️  Setting up database...")
    from sqlalchemy.engine import make_url
    
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
    print("✓ Database ready")


def ensure_recommender_schema():
    """Create enhanced schema with deep learning model storage"""
    print("\n📋 Creating database schema...")
    
    with engine.begin() as conn:
        # User preferences table
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS recommender_user_preferences (
                    customer_id INT PRIMARY KEY,
                    viewed_book_ids TEXT NOT NULL,
                    viewed_book_counts TEXT NULL,
                    purchased_book_counts TEXT NULL,
                    user_embedding LONGTEXT NULL,
                    preference_vector LONGTEXT NULL,
                    total_spent FLOAT DEFAULT 0,
                    purchase_count INT DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NULL
                )
                """
            )
        )
        
        # Recommendation events table
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS recommendation_events (
                    id VARCHAR(36) PRIMARY KEY,
                    customer_id INT NOT NULL,
                    viewed_book_ids TEXT NOT NULL,
                    recommendations TEXT NOT NULL,
                    model_version VARCHAR(50) DEFAULT 'ncf-graph-v1',
                    inference_time_ms FLOAT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_customer (customer_id),
                    INDEX idx_created (created_at)
                )
                """
            )
        )
        
        # Knowledge vectors table
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS recommender_knowledge_vectors (
                    id VARCHAR(128) PRIMARY KEY,
                    entity_type VARCHAR(32) NOT NULL,
                    entity_id VARCHAR(64) NOT NULL,
                    vector_json LONGTEXT NOT NULL,
                    metadata_json LONGTEXT NULL,
                    embedding_model VARCHAR(100),
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_entity (entity_type, entity_id),
                    INDEX idx_updated (updated_at)
                )
                """
            )
        )
        
        # Book catalog table (new)
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS recommender_books (
                    book_id INT PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    author VARCHAR(255),
                    category VARCHAR(100),
                    price FLOAT,
                    rating FLOAT,
                    published_year INT,
                    pages INT,
                    language VARCHAR(50),
                    description LONGTEXT,
                    item_embedding LONGTEXT,
                    metadata_json LONGTEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_category (category),
                    INDEX idx_rating (rating)
                )
                """
            )
        )
        
        # Model metadata table (new)
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS model_metadata (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    model_name VARCHAR(100) NOT NULL,
                    model_version VARCHAR(50),
                    model_type VARCHAR(100),
                    training_samples INT,
                    num_users INT,
                    num_items INT,
                    embedding_dim INT,
                    train_loss FLOAT,
                    val_loss FLOAT,
                    auc_score FLOAT,
                    training_time_seconds FLOAT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_model (model_name, model_version)
                )
                """
            )
        )
        
        # Interaction history table (new)
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS interaction_history (
                    interaction_id INT PRIMARY KEY AUTO_INCREMENT,
                    customer_id INT NOT NULL,
                    book_id INT NOT NULL,
                    event_type VARCHAR(50),
                    rating FLOAT,
                    timestamp DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_customer (customer_id),
                    INDEX idx_book (book_id),
                    INDEX idx_timestamp (timestamp)
                )
                """
            )
        )
    
    print("✓ Schema created")


def populate_books(books: List[Dict]):
    """Populate book catalog"""
    print(f"\n📚 Populating {len(books)} books...")
    
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        from recommender_books import RecommenderBook
        
        existing_count = db.execute(text("SELECT COUNT(*) FROM recommender_books")).scalar()
        
        if existing_count > 0:
            print(f"⚠️  Books already exist ({existing_count}). Skipping population.")
            return
        
        for book in books:
            db.execute(
                text(
                    """
                    INSERT INTO recommender_books 
                    (book_id, title, author, category, price, rating, published_year, pages, language, description)
                    VALUES (:id, :title, :author, :category, :price, :rating, :published_year, :pages, :language, :description)
                    """
                ),
                {
                    "id": book["id"],
                    "title": book["title"],
                    "author": book["author"],
                    "category": book.get("category", "Unknown"),
                    "price": book.get("price", 0),
                    "rating": book.get("rating", 0),
                    "published_year": book.get("published_year", 2024),
                    "pages": book.get("pages", 0),
                    "language": book.get("language", "Vietnamese"),
                    "description": book.get("description", "")
                }
            )
        
        db.commit()
        print(f"✓ Populated {len(books)} books")
    
    except Exception as e:
        db.rollback()
        print(f"✗ Error populating books: {e}")
    
    finally:
        db.close()


def populate_interaction_history(interactions: List[Dict]):
    """Store interaction history in database"""
    print(f"\n📊 Storing {len(interactions)} interaction events...")
    
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        batch_size = 1000
        for i in range(0, len(interactions), batch_size):
            batch = interactions[i:i+batch_size]
            
            for interaction in batch:
                db.execute(
                    text(
                        """
                        INSERT INTO interaction_history 
                        (customer_id, book_id, event_type, rating, timestamp)
                        VALUES (:customer_id, :book_id, :event_type, :rating, :timestamp)
                        """
                    ),
                    {
                        "customer_id": interaction["customer_id"],
                        "book_id": interaction["book_id"],
                        "event_type": interaction["event_type"],
                        "rating": interaction.get("rating_given"),
                        "timestamp": interaction["timestamp"],
                    }
                )
            
            db.commit()
            print(f"  ✓ Stored batch {i//batch_size + 1}/{(len(interactions)-1)//batch_size + 1}")
    
    except Exception as e:
        db.rollback()
        print(f"✗ Error storing interactions: {e}")
    
    finally:
        db.close()


def train_deep_learning_model(interactions: List[Dict], model_dir: str = "models"):
    """Train the deep learning model"""
    print("\n🤖 Training Deep Learning Model...")
    print("   This may take a few minutes...")
    
    try:
        start_time = time.time()
        
        # Initialize and prepare model
        model = NCFGraphRecommenderModel(
            embedding_dim=64,
            num_users=300,
            num_items=2000
        )
        
        # Build model
        model.build_model()
        
        # Prepare training data
        print("\n   📊 Preparing training data...")
        (user_ids, item_ids, context_features), labels, metadata = model.prepare_training_data(interactions)
        print(f"   ✓ Training samples: {metadata['num_samples']}")
        
        # Train
        print("\n   ⏳ Training in progress...")
        history = model.train(user_ids, item_ids, context_features, labels, epochs=15)
        
        training_time = time.time() - start_time
        
        # Get final metrics
        final_val_loss = history.history['val_loss'][-1] if history.history['val_loss'] else 0
        final_auc = history.history['auc'][-1] if 'auc' in history.history else 0
        
        print(f"\n   ✓ Training completed in {training_time:.1f}s")
        print(f"   • Final validation loss: {final_val_loss:.4f}")
        print(f"   • Final AUC score: {final_auc:.4f}")
        
        # Save model
        model.save(model_dir)
        
        # Store model metadata
        store_model_metadata(
            num_samples=metadata['num_samples'],
            train_loss=history.history['loss'][-1],
            val_loss=final_val_loss,
            auc=final_auc,
            training_time=training_time,
            model_dir=model_dir
        )
        
        return model
    
    except ImportError as e:
        print(f"\n⚠️  TensorFlow not available: {e}")
        print("   (This is normal in some environments)")
        return None
    
    except Exception as e:
        print(f"\n✗ Error training model: {e}")
        import traceback
        traceback.print_exc()
        return None


def store_model_metadata(num_samples: int, train_loss: float, val_loss: float, 
                        auc: float, training_time: float, model_dir: str):
    """Store model metadata in database"""
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        db.execute(
            text(
                """
                INSERT INTO model_metadata 
                (model_name, model_version, model_type, training_samples, num_users, num_items, 
                 embedding_dim, train_loss, val_loss, auc_score, training_time_seconds)
                VALUES (:name, :version, :type, :samples, :users, :items, :dim, 
                        :train_loss, :val_loss, :auc, :time)
                """
            ),
            {
                "name": "NCFGraphRecommender",
                "version": "v1.0",
                "type": "Neural Collaborative Filtering + Graph",
                "samples": num_samples,
                "users": 300,
                "items": 2000,
                "dim": 64,
                "train_loss": float(train_loss),
                "val_loss": float(val_loss),
                "auc": float(auc),
                "time": float(training_time)
            }
        )
        db.commit()
        print("✓ Model metadata stored")
    except Exception as e:
        print(f"⚠️  Could not store metadata: {e}")
    finally:
        db.close()


def populate_customer_profiles(customers: List[Dict]):
    """Populate customer profiles in database"""
    print(f"\n👥 Populating {len(customers)} customer profiles...")
    
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        from app import UserPreferenceRow, _dump_count_map
        
        existing_count = db.execute(
            text("SELECT COUNT(*) FROM recommender_user_preferences")
        ).scalar()
        
        if existing_count > 0:
            print(f"⚠️  Profiles already exist ({existing_count}). Skipping population.")
            return
        
        for customer in customers:
            view_counts = {}
            for book_id in customer.get("viewed_books", []):
                view_counts[book_id] = view_counts.get(book_id, 0) + 1
            
            purchase_counts = {}
            for book_id in customer.get("purchased_books", []):
                purchase_counts[book_id] = purchase_counts.get(book_id, 0) + 1
            
            db.add(
                UserPreferenceRow(
                    customer_id=customer["customer_id"],
                    viewed_book_ids=json.dumps(customer.get("viewed_books", [])),
                    viewed_book_counts=_dump_count_map(view_counts),
                    purchased_book_counts=_dump_count_map(purchase_counts),
                    updated_at=datetime.utcnow(),
                )
            )
        
        db.commit()
        print(f"✓ Populated {len(customers)} customer profiles")
    
    except Exception as e:
        db.rollback()
        print(f"✗ Error populating customers: {e}")
    
    finally:
        db.close()


def print_statistics(books: List[Dict], customers: List[Dict], interactions: List[Dict]):
    """Print system statistics"""
    print("\n" + "="*60)
    print("📊 RECOMMENDER AI SYSTEM STATISTICS")
    print("="*60)
    
    # Books stats
    categories = {}
    for book in books:
        cat = book.get("category", "Unknown")
        categories[cat] = categories.get(cat, 0) + 1
    
    print("\n📚 Book Catalog:")
    print(f"  • Total books: {len(books)}")
    print(f"  • Categories: {len(categories)}")
    for cat, count in sorted(categories.items()):
        print(f"    - {cat}: {count}")
    
    avg_price = sum(b.get("price", 0) for b in books) / len(books)
    print(f"  • Average price: ${avg_price:.2f}")
    
    # Customer stats
    print(f"\n👥 Customer Base:")
    print(f"  • Total customers: {len(customers)}")
    avg_views = sum(len(c.get("viewed_books", [])) for c in customers) / len(customers)
    avg_purchases = sum(c.get("purchase_count", 0) for c in customers) / len(customers)
    total_revenue = sum(c.get("total_spent", 0) for c in customers)
    
    print(f"  • Avg views per customer: {avg_views:.1f}")
    print(f"  • Avg purchases per customer: {avg_purchases:.1f}")
    print(f"  • Total revenue: ${total_revenue:,.2f}")
    
    # Interaction stats
    print(f"\n📊 Interaction Data:")
    print(f"  • Total interactions: {len(interactions)}")
    
    view_count = sum(1 for i in interactions if i["event_type"] == "view")
    purchase_count = sum(1 for i in interactions if i["event_type"] == "purchase")
    print(f"  • Views: {view_count}")
    print(f"  • Purchases: {purchase_count}")
    print(f"  • Engagement rate: {100*purchase_count/len(interactions):.1f}%")
    
    sparsity = 1 - (len(interactions) / (len(customers) * len(books)))
    print(f"  • Matrix sparsity: {100*sparsity:.2f}%")
    
    print("\n✅ System is ready for production use!")
    print("="*60)


def main():
    """Main initialization function"""
    print("\n" + "="*60)
    print("🚀 ADVANCED RECOMMENDER AI SERVICE INITIALIZATION")
    print("="*60)
    print("\n⏳ This process will:")
    print("  1. Generate 2000+ realistic books")
    print("  2. Create 300+ customer profiles with behavior")
    print("  3. Train a deep learning NCF+GNN model")
    print("  4. Populate the database")
    print("\nStarting...")
    
    try:
        # Setup database
        ensure_database_exists(DB_URL)
        ensure_recommender_schema()
        
        # Generate dataset
        print("\n" + "-"*60)
        print("🎲 GENERATING LARGE-SCALE DATASET")
        print("-"*60)
        
        print("\n📚 Generating 2000 books...")
        books = generate_books(2000)
        
        print("👥 Generating 300 customers with realistic behavior...")
        customers, interactions = generate_customer_behavior(books, num_customers=300)
        
        # Save dataset locally (for debugging)
        # save_dataset(books, customers, interactions, output_dir="data")
        
        # Populate database
        print("\n" + "-"*60)
        print("💾 POPULATING DATABASE")
        print("-"*60)
        
        populate_books(books)
        populate_customer_profiles(customers)
        populate_interaction_history(interactions)
        
        # Train deep learning model
        print("\n" + "-"*60)
        print("🧠 TRAINING DEEP LEARNING MODEL")
        print("-"*60)
        
        model = train_deep_learning_model(interactions, model_dir="/tmp/recommender_models")
        
        # Print statistics
        print_statistics(books, customers, interactions)
        
        print("\n✅ Advanced recommender system initialization complete!")
        print("The system will now start serving recommendations using the trained model.")
        
    except Exception as e:
        print(f"\n✗ Error during initialization: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
