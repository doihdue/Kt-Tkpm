"""
Advanced Deep Learning Recommender Model
Neural Collaborative Filtering + Graph-inspired Approach
"""

import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers, Model
from tensorflow.keras.optimizers import Adam
from sklearn.preprocessing import MinMaxScaler
import json
from typing import Tuple, List, Dict
import os


class NCFGraphRecommenderModel:
    """
    Hybrid Neural Collaborative Filtering model with Graph-inspired components
    Combines:
    1. Neural Collaborative Filtering (user-item interactions)
    2. Content-based features (item metadata)
    3. Graph collaborative signals (user similarity patterns)
    """
    
    def __init__(self, 
                 embedding_dim: int = 64,
                 num_users: int = 300,
                 num_items: int = 2000):
        self.embedding_dim = embedding_dim
        self.num_users = num_users
        self.num_items = num_items
        self.model = None
        self.user_model = None
        self.item_model = None
        self.scaler = MinMaxScaler()
        
    def build_model(self):
        """Build the hybrid NCF + GNN model"""
        
        # ===== User Input Branch =====
        user_input = keras.Input(shape=(1,), dtype=tf.int32, name='user_input')
        user_embedding = layers.Embedding(
            input_dim=self.num_users + 1,
            output_dim=self.embedding_dim,
            name='user_embedding'
        )(user_input)
        user_embedding = layers.Flatten()(user_embedding)
        
        # User deep network
        user_mlp = layers.Dense(256, activation='relu')(user_embedding)
        user_mlp = layers.BatchNormalization()(user_mlp)
        user_mlp = layers.Dropout(0.3)(user_mlp)
        user_mlp = layers.Dense(128, activation='relu')(user_mlp)
        user_mlp = layers.BatchNormalization()(user_mlp)
        user_mlp = layers.Dropout(0.3)(user_mlp)
        user_mlp = layers.Dense(64, activation='relu')(user_mlp)
        
        # ===== Item Input Branch =====
        item_input = keras.Input(shape=(1,), dtype=tf.int32, name='item_input')
        item_embedding = layers.Embedding(
            input_dim=self.num_items + 1,
            output_dim=self.embedding_dim,
            name='item_embedding'
        )(item_input)
        item_embedding = layers.Flatten()(item_embedding)
        
        # Item deep network
        item_mlp = layers.Dense(256, activation='relu')(item_embedding)
        item_mlp = layers.BatchNormalization()(item_mlp)
        item_mlp = layers.Dropout(0.3)(item_mlp)
        item_mlp = layers.Dense(128, activation='relu')(item_mlp)
        item_mlp = layers.BatchNormalization()(item_mlp)
        item_mlp = layers.Dropout(0.3)(item_mlp)
        item_mlp = layers.Dense(64, activation='relu')(item_mlp)
        
        # ===== Interaction Features Branch =====
        # This captures collaborative signals and interaction patterns
        context_input = keras.Input(shape=(8,), dtype=tf.float32, name='context_input')
        context_mlp = layers.Dense(64, activation='relu')(context_input)
        context_mlp = layers.BatchNormalization()(context_mlp)
        context_mlp = layers.Dropout(0.2)(context_mlp)
        context_mlp = layers.Dense(32, activation='relu')(context_mlp)
        
        # ===== Fusion Layer (Graph-inspired collaborative component) =====
        # Combine all representations
        concatenated = layers.Concatenate()([user_mlp, item_mlp, context_mlp])
        
        # Deep fusion network
        fusion = layers.Dense(256, activation='relu')(concatenated)
        fusion = layers.BatchNormalization()(fusion)
        fusion = layers.Dropout(0.3)(fusion)
        fusion = layers.Dense(128, activation='relu')(fusion)
        fusion = layers.BatchNormalization()(fusion)
        fusion = layers.Dropout(0.3)(fusion)
        fusion = layers.Dense(64, activation='relu')(fusion)
        fusion = layers.BatchNormalization()(fusion)
        fusion = layers.Dropout(0.2)(fusion)
        
        # Output layer - predict interaction strength (0-1)
        output = layers.Dense(1, activation='sigmoid', name='output')(fusion)
        
        # Build the complete model
        self.model = Model(
            inputs=[user_input, item_input, context_input],
            outputs=output,
            name='NCFGraphRecommender'
        )
        
        # Compile with appropriate optimizer and loss
        self.model.compile(
            optimizer=Adam(learning_rate=0.001),
            loss='binary_crossentropy',
            metrics=['mse', tf.keras.metrics.AUC()]
        )
        
        print("✓ Model architecture built successfully")
        self.model.summary()
        
    def prepare_training_data(self, interactions: List[Dict]) -> Tuple[Tuple, np.ndarray, Dict]:
        """
        Prepare training data from interaction events
        Returns: (inputs_tuple, labels, metadata)
        """
        user_ids = []
        item_ids = []
        context_features = []
        labels = []
        
        # Aggregate data
        interaction_strength = {}  # (user, item) -> strength
        user_item_counts = {}
        item_view_counts = {}
        user_view_history = {}
        
        for interaction in interactions:
            user_id = interaction["customer_id"]
            item_id = interaction["book_id"]
            event_type = interaction["event_type"]
            
            key = (user_id, item_id)
            
            # Assign strength based on type
            if key not in interaction_strength:
                interaction_strength[key] = 0
            
            if event_type == "view":
                interaction_strength[key] += 0.3
            elif event_type == "purchase":
                interaction_strength[key] += 0.8
                
            # Count interactions
            user_item_counts[key] = user_item_counts.get(key, 0) + 1
            item_view_counts[item_id] = item_view_counts.get(item_id, 0) + 1
            
            if user_id not in user_view_history:
                user_view_history[user_id] = []
            user_view_history[user_id].append(item_id)
        
        # Create training samples
        for (user_id, item_id), strength in interaction_strength.items():
            user_ids.append(user_id)
            item_ids.append(item_id)
            
            # Extract context features
            user_history_size = len(user_view_history.get(user_id, []))
            item_popularity = item_view_counts.get(item_id, 1)
            interaction_count = user_item_counts[(user_id, item_id)]
            
            # Calculate complementary features
            user_diversity = len(set(user_view_history.get(user_id, [])))
            time_factor = min(interaction_count / 5, 1.0)  # Normalize
            
            context = [
                min(user_history_size / 50, 1.0),  # User activity (normalized)
                min(item_popularity / 100, 1.0),  # Item popularity (normalized)
                min(interaction_count / 3, 1.0),  # Interaction frequency
                min(user_diversity / 50, 1.0),  # User diversity
                time_factor,  # Recency/frequency
                np.tanh(user_history_size / 50),  # Tanh normalization
                np.tanh(item_popularity / 100),  # Tanh normalization
                min(strength, 1.0)  # Interaction type strength
            ]
            
            context_features.append(context)
            labels.append(min(strength, 1.0))  # Cap at 1.0
        
        # Convert to numpy arrays
        user_ids = np.array(user_ids, dtype=np.int32)
        item_ids = np.array(item_ids, dtype=np.int32)
        context_features = np.array(context_features, dtype=np.float32)
        labels = np.array(labels, dtype=np.float32)
        
        # Normalize context features
        context_features = self.scaler.fit_transform(context_features)
        
        inputs = (user_ids, item_ids, context_features)
        
        metadata = {
            "num_samples": len(user_ids),
            "num_users": self.num_users,
            "num_items": self.num_items,
            "user_history": user_view_history,
            "item_popularity": item_view_counts,
            "interaction_strength": interaction_strength
        }
        
        return inputs, labels, metadata
    
    def train(self, 
              user_ids: np.ndarray,
              item_ids: np.ndarray,
              context_features: np.ndarray,
              labels: np.ndarray,
              epochs: int = 20,
              batch_size: int = 256,
              validation_split: float = 0.2):
        """Train the model"""
        
        if self.model is None:
            self.build_model()
        
        print("\n🤖 Training NCF+Graph Hybrid Model...")
        
        history = self.model.fit(
            [user_ids, item_ids, context_features],
            labels,
            epochs=epochs,
            batch_size=batch_size,
            validation_split=validation_split,
            verbose=1,
            callbacks=[
                keras.callbacks.EarlyStopping(
                    monitor='val_loss',
                    patience=3,
                    restore_best_weights=True
                ),
                keras.callbacks.ReduceLROnPlateau(
                    monitor='val_loss',
                    factor=0.5,
                    patience=2,
                    min_lr=0.00001
                )
            ]
        )
        
        return history
    
    def predict_batch(self,
                     user_ids: List[int],
                     candidate_items: List[int],
                     context_features: np.ndarray) -> np.ndarray:
        """Predict scores for multiple user-item pairs"""
        
        if self.model is None:
            raise ValueError("Model must be built first")
        
        user_array = np.array(user_ids, dtype=np.int32)
        item_array = np.array(candidate_items, dtype=np.int32)
        
        predictions = self.model.predict([user_array, item_array, context_features], verbose=0)
        return predictions.flatten()
    
    def save(self, path: str):
        """Save model and scaler"""
        os.makedirs(path, exist_ok=True)
        
        if self.model is not None:
            self.model.save(os.path.join(path, 'ncf_graph_model.h5'))
            
            # Save scaler parameters
            scaler_data = {
                'data_min': self.scaler.data_min_.tolist(),
                'data_max': self.scaler.data_max_.tolist(),
                'data_range': self.scaler.data_range_.tolist()
            }
            with open(os.path.join(path, 'scaler.json'), 'w') as f:
                json.dump(scaler_data, f)
        
        print(f"✓ Model saved to {path}")
    
    def load(self, path: str):
        """Load model and scaler"""
        model_path = os.path.join(path, 'ncf_graph_model.h5')
        scaler_path = os.path.join(path, 'scaler.json')
        
        if os.path.exists(model_path):
            self.model = keras.models.load_model(model_path)
            print(f"✓ Model loaded from {model_path}")
        
        if os.path.exists(scaler_path):
            with open(scaler_path, 'r') as f:
                scaler_data = json.load(f)
            self.scaler.data_min_ = np.array(scaler_data['data_min'])
            self.scaler.data_max_ = np.array(scaler_data['data_max'])
            self.scaler.data_range_ = np.array(scaler_data['data_range'])
    
    def get_user_embedding(self, user_id: int) -> np.ndarray:
        """Extract user embedding from trained model"""
        if self.model is None:
            raise ValueError("Model must be trained first")
        
        # Get embedding from model
        embedding_layer = self.model.get_layer('user_embedding')
        embeddings = embedding_layer.get_weights()[0]
        return embeddings[user_id]
    
    def get_item_embedding(self, item_id: int) -> np.ndarray:
        """Extract item embedding from trained model"""
        if self.model is None:
            raise ValueError("Model must be trained first")
        
        # Get embedding from model
        embedding_layer = self.model.get_layer('item_embedding')
        embeddings = embedding_layer.get_weights()[0]
        return embeddings[item_id]


def train_and_save_model(interactions: List[Dict],
                        model_dir: str = "models"):
    """Train model and save it"""
    
    # Initialize model
    model = NCFGraphRecommenderModel(
        embedding_dim=64,
        num_users=300,
        num_items=2000
    )
    
    # Build model
    model.build_model()
    
    # Prepare training data
    print("\n📊 Preparing training data...")
    (user_ids, item_ids, context_features), labels, metadata = model.prepare_training_data(interactions)
    print(f"✓ Prepared {metadata['num_samples']} training samples")
    
    # Train model
    history = model.train(user_ids, item_ids, context_features, labels, epochs=20)
    
    # Save model
    model.save(model_dir)
    
    return model


if __name__ == "__main__":
    print("🧠 NCF + Graph Recommender Model")
    
    # Create sample data
    interactions = [
        {"customer_id": 1, "book_id": 101, "event_type": "view"},
        {"customer_id": 1, "book_id": 101, "event_type": "purchase"},
        {"customer_id": 1, "book_id": 102, "event_type": "view"},
        {"customer_id": 2, "book_id": 101, "event_type": "view"},
        {"customer_id": 2, "book_id": 103, "event_type": "purchase"},
    ]
    
    # Train model
    model = train_and_save_model(interactions)
