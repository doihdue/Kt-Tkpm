# Recommender AI Service 🤖📚

Advanced AI-powered book recommendation engine for the Bookstore Microservices platform.

## Features

- **Hybrid Recommendation Algorithm**: Combines content-based filtering, collaborative filtering, and popularity scoring
- **Real-time Learning**: Tracks customer viewing and purchase behavior
- **Vector Embeddings**: Uses AI transformers (or hash-based fallback) for semantic similarity
- **Personalization**: Different recommendations for each customer based on their preferences
- **Cold-Start Handling**: Works even for new customers without history

## Architecture

```
Customer Behavior → User Preferences DB
                  ↓
            Knowledge Base (Product Vectors)
                  ↓
    Hybrid Algorithm (Content + Collab + Popularity)
                  ↓
            Personalized Recommendations
```

### Algorithm Weights
- Content-based similarity: **65%**
- Collaborative filtering: **25%**
- Popularity boost: **10%**

## API Endpoints

### 1. Get Personalized Recommendations
```bash
POST /api/recommendations
Content-Type: application/json

{
  "customer_id": 1,
  "viewed_book_ids": [1, 2, 3],
  "purchased_book_ids": [1]
}

Response:
[
  {
    "book_id": 5,
    "score": 0.8234,
    "reason": "Similar to your interests: python, technology"
  },
  ...
]
```

### 2. Track Customer View Event
```bash
POST /api/recommendations/track-view
Content-Type: application/json

{
  "customer_id": 1,
  "book_id": 5
}

Response: {"ok": true}
```

### 3. Get Recommendation History
```bash
GET /api/recommendations/history?customer_id=1&limit=20

Response:
[
  {
    "id": "uuid",
    "customer_id": 1,
    "viewed_book_ids": [1, 2, 3],
    "recommendations": [...],
    "created_at": "2026-04-06T10:30:00"
  },
  ...
]
```

### 4. Sync Knowledge Base
```bash
POST /api/ai/knowledge/sync?customer_id=1

Response:
{
  "ok": true,
  "model_source": "transformer|hash-fallback",
  "product_vectors": 150,
  "customer_id": 1
}
```

### 5. AI Chat for Book Recommendations
```bash
POST /api/ai/chat
Content-Type: application/json

{
  "customer_id": 1,
  "message": "I'm looking for technical books about Python",
  "top_k": 3
}

Response:
{
  "answer": "Based on your interests...",
  "retrieved_products": [...],
  "model_source": "transformer"
}
```

### 6. Health Check
```bash
GET /api/recommendations/health

Response:
{
  "service": "recommender-ai-service",
  "status": "ok",
  "ai_mode": "transformer|hash-fallback",
  "embedding_model": "sentence-transformers/all-MiniLM-L6-v2"
}
```

## Installation & Setup

### 1. Install Dependencies
```bash
cd recommender-ai-service
pip install -r requirements.txt
```

### 2. Initialize Database
The initialization runs automatically when the Docker container starts:

```bash
python init_recommender.py
```

This will:
- Create the MySQL database and tables
- Fetch books from book-service
- Build AI vectors for all products
- Create sample customer profiles for testing

### 3. Run Locally
```bash
export DB_URL="mysql+pymysql://root:123456@localhost:3306/recommender_db"
export BOOK_SERVICE_URL="http://localhost:8000"
export ORDER_SERVICE_URL="http://localhost:8000"

python init_recommender.py  # One-time initialization
uvicorn app:app --reload --port 8000
```

### 4. Docker Deployment
```bash
docker-compose up recommender-ai-service
```

## Database Schema

### `recommender_user_preferences`
Stores customer viewing and purchase history

```sql
CREATE TABLE recommender_user_preferences (
    customer_id INT PRIMARY KEY,
    viewed_book_ids TEXT NOT NULL,           -- JSON list of viewed book IDs
    viewed_book_counts TEXT NULL,            -- JSON dict of view counts
    purchased_book_counts TEXT NULL,         -- JSON dict of purchase counts
    updated_at DATETIME NULL
);
```

### `recommendation_events`
Audit log of all recommendation requests

```sql
CREATE TABLE recommendation_events (
    id VARCHAR(36) PRIMARY KEY,
    customer_id INT NOT NULL,
    viewed_book_ids TEXT NOT NULL,           -- Books viewed at time of request
    recommendations TEXT NOT NULL,           -- Returned recommendations (JSON)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_customer (customer_id),
    INDEX idx_created (created_at)
);
```

### `recommender_knowledge_vectors`
Vector embeddings for products and users

```sql
CREATE TABLE recommender_knowledge_vectors (
    id VARCHAR(128) PRIMARY KEY,             -- Format: "entity_type:entity_id"
    entity_type VARCHAR(32) NOT NULL,        -- "product" or "user"
    entity_id VARCHAR(64) NOT NULL,
    vector_json LONGTEXT NOT NULL,           -- Dense vector (list of floats)
    metadata_json LONGTEXT NULL,             -- Book title, category, etc.
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_entity (entity_type, entity_id),
    INDEX idx_updated (updated_at)
);
```

## Integration with API Gateway

The API Gateway calls the recommender service at:

1. **Home Page** (`GET /`):
   - Calls `/api/recommendations` to get personalized recommendations for logged-in customers
   - Displays 4-5 recommended books below featured books

2. **Book Detail Page** (`GET /books/{id}`):
   - Calls `/api/recommendations/track-view` to track the viewing
   - Tracks in-memory recent views in session

3. **Data Synchronization**:
   - Fetches customer purchase history from order-service
   - Uses it to enhance personalization

## Embedding Models

### Primary: SentenceTransformers
- Model: `sentence-transformers/all-MiniLM-L6-v2`
- Dimensions: 384 (default)
- Best for: Semantic similarity across text

### Fallback: Hash-Based Embedding
Used when SentenceTransformers is unavailable:
- Tokenizes text (lowercase, alphanumeric)
- Creates fixed-size vector based on token hash
- Fast and lightweight

## Performance Tuning

### Reduce Latency
```python
# Use smaller embedding model
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"  # Already lightweight

# Limit max results
RECOMMENDATION_LIMIT = 5
```

### Improve Accuracy
```python
# Increase vector dimension (requires more memory/CPU)
EMBEDDING_DIM = 128

# Adjust algorithm weights
CONTENT_WEIGHT = 0.70        # Increase for content-based focus
COLLAB_WEIGHT = 0.20         # Increase for collaborative strength
POPULARITY_WEIGHT = 0.10     # Popular items in recommendations
```

### Cold-Start Strategy
For new customers (no history):
1. Show popular/trending books
2. Ask for initial preferences
3. Use popularity-based recommendations until enough data

## Sample Customer Profiles

The initialization creates 5 sample customers:

| ID | Name | Interests | Purchase History |
|----|------|-----------|------------------|
| 1 | Tech Enthusiast | Python, ML, Clean Code | Python for DS |
| 2 | Business Reader | Business, Productivity | Business Strategy |
| 3 | Fiction Lover | Fiction, Mystery | Mystery Tales |
| 4 | Mixed Reader | Various | Python, ML books |
| 5 | Data Scientist | Python, ML, Code | All tech books |

Test recommendations with these customer IDs!

## Troubleshooting

### Issue: No Recommendations Returned
**Solution**: 
- Ensure books exist in book-service
- Run `init_recommender.py` to sync product vectors
- Check database connection with `GET /api/recommendations/health`

### Issue: All Recommendations Same Score
**Solution**:
- Increase algorithm diversity
- Use different embedding model
- Check if customer has enough history

### Issue: Slow Recommendations
**Solution**:
- Use hash-based fallback temporarily
- Limit number of candidates evaluated
- Cache vector embeddings

### Issue: SentenceTransformers Not Loaded
**Fallback**: Service automatically uses hash-based embeddings
- Check logs: `docker logs recommender-ai-service`
- Python version compatibility: `python --version` (3.8+)

## Development & Testing

### Run Unit Tests
```bash
python -m pytest tests/
```

### Manual Test
```bash
curl -X POST http://localhost:8000/api/recommendations \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": 1,
    "viewed_book_ids": [1, 2, 3],
    "purchased_book_ids": [1]
  }'
```

### Monitor Logs
```bash
docker logs recommender-ai-service -f
```

## Future Enhancements

- [ ] Real-time recommendation updates (WebSocket)
- [ ] A/B testing framework
- [ ] Multi-language support with multilingual embeddings
- [ ] Deep learning models (neural collaborative filtering)
- [ ] Explainable AI dashboard
- [ ] Feedback loop from user clicks/purchases
- [ ] Batch recommendation pre-computation
- [ ] Redis caching for hot recommendations

## License

MIT License - Part of Bookstore Microservices

## Support

For issues or feature requests, open an issue in the main repository.
