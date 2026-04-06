# 🧠 Advanced Recommender AI System (Deep Learning Edition)

Hệ thống recommender AI thế hệ mới với Deep Learning - được xây dựng để xử lý **2000+ sách** và **300+ khách hàng** với **Neural Collaborative Filtering + Graph Networks**.

## 🎯 Tổng Quan

### Kiến Trúc Hybrid Deep Learning

```text
┌─────────────────────────────────────────────────────────┐
│                 Input Layer                              │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────┐        │
│  │  User ID │  │ Item ID  │  │ Context Features│        │
│  └────┬─────┘  └────┬─────┘  └────────┬────────┘        │
└────────┼─────────────┼────────────────┼────────────────┘
         │ Embedding   │ Embedding      │
         ▼             ▼                ▼
┌──────────────────────────────────────────────────────────┐
│         Deep Neural Networks (MLP Layers)               │
│                                                           │
│  User Branch:    Item Branch:      Context Branch:      │
│  256 → ReLU      256 → ReLU        64 → ReLU            │
│  ↓ BatchNorm     ↓ BatchNorm       ↓ BatchNorm         │
│  128 → ReLU      128 → ReLU        32 → ReLU            │
│  ↓ Dropout       ↓ Dropout         ↓ Dropout           │
│  64 → ReLU       64 → ReLU                              │
└────────┬─────────────┬──────────────┬───────────────────┘
         │             │              │
         └─────────────┼──────────────┘
                       ▼
          ┌────────────────────────┐
          │  Fusion Layer (Concat) │
          └────────────┬───────────┘
                       ▼
        ┌──────────────────────────┐
        │ Deep Fusion Network      │
        │ 256 → ReLU + BatchNorm   │
        │ 128 → ReLU + BatchNorm   │
        │ 64  → ReLU + BatchNorm   │
        └────────────┬─────────────┘
                     ▼
          ┌──────────────────────┐
          │  Output (Sigmoid)    │
          │ Interaction Score    │
          │ (0.0 - 1.0)          │
          └──────────────────────┘
```

### Thành Phần Chính

| Thành Phần | Mô Tả | Kích Thước |
|-----------|-------|-----------|
| User Embedding | Học đặc tính người dùng | 64D |
| Item Embedding | Học đặc tính sách | 64D |
| User MLP | Mạng sâu xử lý user | 256→128→64 |
| Item MLP | Mạng sâu xử lý item | 256→128→64 |
| Context Features | Tín hiệu hợp tác | 8D |
| Fusion Network | Kết hợp tất cả tín hiệu | 256→128→64 |

## 📊 Dataset

### Kích Thước Dataset
- **2000+ sách** ✅
- **300+ khách hàng** ✅  
- **5000+ sự kiện tương tác** ✅

### Phân Loại Sách
```
Technology   (Python, Java, Go, Rust...)      → 400 sách
Fiction      (Mystery, Adventure, Drama...)   → 400 sách
Business     (Startup, Strategy, Finance...)  → 350 sách
Self-Help    (Habits, Mindset, Growth...)     → 350 sách
Science      (Physics, Biology, Psychology)  → 300 sách
History      (World, Civilization, Era...)    → 200 sách
```

### Hành Vi Khách Hàng
```
Customer Persona        Views/Khách    Purchase Rate    Budget
────────────────────────────────────────────────────────────
Tech Enthusiast         15-40          50%              $30-150
Business Professional   10-30          40%              $20-120
Science Nerd            20-50          45%              $25-140
Fiction Lover           25-60          55%              $15-100
Self-Improvement Seeker 15-35          48%              $20-130
History Buff            20-45          42%              $20-110
Curious Mind            30-70          50%              $25-150
```

## 🚀 Cài Đặt & Chạy

### Phương Pháp 1: Docker Compose (Khuyến Nghị)

```bash
# Chạy với advanced profile
docker-compose --profile advanced up recommender-ai-service

# Logs
docker logs recommender-ai-service -f
```

Quá trình này sẽ:
1. ⏳ Tạo 2000+ sách (dùng 30 giây)
2. 👥 Tạo 300+ khách hàng + hành vi (dùng 20 giây)
3. 🤖 Train deep learning model (dùng 3-5 phút)
4. 💾 Lưu model và dữ liệu (dùng 30 giây)
5. 🚀 Khởi động service (dùng 10 giây)

**Tổng thời gian: 5-7 phút**

### Phương Pháp 2: Local Development

```bash
# 1. Cài đặt dependencies
cd recommender-ai-service
pip install -r requirements.txt

# 2. Khởi tạo database
python init_recommender_advanced.py

# 3. Chạy service
uvicorn app:app --reload --port 8000
```

### Phương Pháp 3: Chỉ GenerateDataset (Không Training)

```bash
python dataset_generator.py

# Output:
# books.json       (2000 sách)
# customers.json   (300 khách hàng) 
# events.json      (5000+ sự kiện)
```

## 🧠 Model Deep Learning

### Architecture Details

**Neural Collaborative Filtering (NCF)**
- Kết hợp 2 phương pháp:
  1. **Embedding-based** - Học latent factors
  2. **MLP-based** - Học non-linear interactions

**Graph-Inspired Component**
- Collaborative signals từ purchase patterns
- User-user similarity từ shared interactions
- Item-item similarity từ co-purchase data

### Hyperparameters

```python
# Model Configuration
embedding_dim = 64          # Embedding space dimension
num_users = 300             # Số user
num_items = 2000            # Số items

# Network Layers
user_mlp = [256, 128, 64]   # User branch
item_mlp = [256, 128, 64]   # Item branch
fusion_mlp = [256, 128, 64] # Fusion network

# Training
learning_rate = 0.001
batch_size = 256
epochs = 15-20
validation_split = 0.2

# Regularization
dropout_rate = 0.2-0.3
batch_norm = True
early_stopping = True
```

### Training Results (Dự Kiến)

```
Epoch 1/15
Training Loss: 0.4521 | Val Loss: 0.3812 | AUC: 0.7234
Epoch 5/15
Training Loss: 0.2134 | Val Loss: 0.2456 | AUC: 0.8512
Epoch 10/15
Training Loss: 0.1523 | Val Loss: 0.1987 | AUC: 0.8923
Epoch 15/15
Training Loss: 0.1234 | Val Loss: 0.1654 | AUC: 0.9124

✓ Final AUC Score: 0.9124
✓ Training Time: 3mn 45s
```

## 📡 API Usage

### 1. Lấy Gợi Ý (Sử Dụng Deep Learning Model)

```bash
curl -X POST http://localhost:8011/api/recommendations \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": 1,
    "viewed_book_ids": [101, 102, 103],
    "purchased_book_ids": [101]
  }'

Response:
[
  {
    "book_id": 205,
    "score": 0.9124,
    "reason": "Matches your deep-learning analyzed preferences"
  },
  {
    "book_id": 312,
    "score": 0.8756,
    "reason": "Similar to books you've purchased"
  }
]
```

### 2. Lưu Lại Xem Sách

```bash
curl -X POST http://localhost:8011/api/recommendations/track-view \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": 1,
    "book_id": 205
  }'
```

### 3. Kiểm Tra Health & Model Info

```bash
curl http://localhost:8011/api/recommendations/health

Response:
{
  "service": "recommender-ai-service",
  "status": "ok",
  "ai_mode": "transformer",
  "model_type": "NCF+Graph",
  "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
  "num_users_trained": 300,
  "num_items_trained": 2000,
  "model_version": "v1.0"
}
```

### 4. Lịch Sử Gợi Ý

```bash
curl "http://localhost:8011/api/recommendations/history?customer_id=1&limit=10"
```

## 🗂️ Cấu Trúc Files

```
recommender-ai-service/
├── app.py                        # FastAPI main application
├── deep_learning_model.py        # NCF+Graph model architecture
├── dataset_generator.py          # Dataset generation logic
├── init_recommender_advanced.py  # Advanced initialization script
├── recommender_models.py         # SQLAlchemy ORM models
│
├── requirements.txt              # Python dependencies
├── Dockerfile                    # Optimized for deep learning
│
├── models/                       # Saved trained models
│   ├── ncf_graph_model.h5       # Keras model
│   └── scaler.json              # Feature scaler
│
├── data/                         # Generated datasets
│   ├── books.json               # Book catalog
│   ├── customers.json           # Customer profiles
│   └── events.json              # Interaction history
│
└── README_ADVANCED.md            # This file
```

## 💡 Tối Ưu Hiệu Suất

### Để Tăng Tốc Độ

1. **Giảm số epoch**
   ```python
   epochs = 5  # Quick training (thay vì 15-20)
   ```

2. **Giảm batch size**
   ```python
   batch_size = 512
   ```

3. **Dùng GPU** (nếu có)
   ```bash
   export TF_FORCE_GPU_ALLOW_GROWTH=true
   ```

### Để Cải Thiện Độ Chính Xác

1. **Tăng embedding dimension**
   ```python
   embedding_dim = 128  # (thay vì 64)
   ```

2. **Thêm data augmentation**
   - Tạo thêm sự kiện từ implicit feedback
   - Thêm negative sampling

3. **Tuning learning rate**
   ```python
   learning_rate = 0.0005  # Start lower
   ```

4. **Ensemble predictions**
   - Kết hợp NCF + content-based + collaborative

## 🐛 Troubleshooting

### ❌ TensorFlow không load

```
⚠️  TensorFlow not available
   → Hệ thống sẽ dùng hybrid mode không Deep Learning
   → Cài: pip install tensorflow
```

### ❌ Memory quá hạn

```
Solution:
- Giảm embedding_dim: 64 → 32
- Giảm batch_size: 256 → 128
- Giảm num_users hoặc num_items
```

### ❌ Training quá lâu

```
Solution:
- Giảm epochs: 20 → 10
- Giảm dataset: 300 customers → 100
- Tăng batch_size: 256 → 512
```

### ❌ Low accuracy (AUC < 0.70)

```
Solution:
- Kiểm tra data quality: events.json
- Tăng epochs: 15 → 25
- Thêm data: tạo 500+ customers
- Tune learning_rate: 0.001 → 0.0005
```

## 📈 Monitoring & Analytics

### Database Queries

```sql
-- Hiện trạng model
SELECT * FROM model_metadata 
ORDER BY created_at DESC LIMIT 1;

-- Người dùng hoạt động nhất
SELECT customer_id, COUNT(*) as interactions 
FROM interaction_history 
GROUP BY customer_id 
ORDER BY interactions DESC 
LIMIT 10;

-- Sách phổ biến nhất
SELECT book_id, COUNT(*) as views 
FROM interaction_history 
WHERE event_type = 'view'
GROUP BY book_id 
ORDER BY views DESC 
LIMIT 10;

-- Tỷ lệ conversion
SELECT 
  (SELECT COUNT(*) FROM interaction_history WHERE event_type = 'purchase') / 
  (SELECT COUNT(*) FROM interaction_history WHERE event_type = 'view') as conversion_rate;
```

## 🚀 Production Deployment

### Scaling Recommendations

1. **Model Caching**
   ```python
   # Load model once, reuse for predictions
   MODEL = tf.keras.models.load_model("models/ncf_graph_model.h5")
   ```

2. **Batch Prediction**
   ```python
   # Predict for 100 users at once
   predictions = MODEL.predict([user_ids, item_ids, features])
   ```

3. **Redis Cache**
   ```python
   # Cache hot recommendations
   recommendations = redis.get(f"rec:user:{user_id}:top5")
   ```

4. **Async Processing**
   ```python
   # Background: retrain model every day
   @scheduler.scheduled_job('cron', hour=2)
   def retrain_model():
       # Fetch new interactions
       # Retrain model
       # Save to disk
   ```

## 📚 References

- [Neural Collaborative Filtering (He et al., 2017)](https://arxiv.org/abs/1708.05024)
- [TensorFlow Recommendersystems](https://www.tensorflow.org/recommenders)
- [Recommendation Systems Book by Aggarwal](https://www.springer.com/gp/book/9783319296579)

## 📝 License

MIT License - Phần của Bookstore Microservices

## 🆘 Support

Cần giúp? Tạo issue hoặc liên hệ development team! 🎉
