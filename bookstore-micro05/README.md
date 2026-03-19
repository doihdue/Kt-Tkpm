# Bookstore Microservices Project

Một dự án microservices được xây dựng bằng Django và FastAPI cho một hiệu sách trực tuyến với nhiều dịch vụ độc lập.

## Required Services
1. **customer-service**: Quản lý đăng ký và thông tin khách hàng (Django)
2. **cart-service**: Quản lý giỏ hàng (Django)
3. **book-service**: Quản lý sách và tồn kho (Django)
4. **staff-service**: Quản lý nhân viên (Django)
5. **order-service**: Quản lý đơn hàng (FastAPI)
6. **payment-service**: Xử lý thanh toán đơn hàng (FastAPI)
7. **shipping-service**: Xử lý vận chuyển đơn hàng (FastAPI)
8. **manager-service**: Quản lý tác vụ vận hành và quản trị (FastAPI)
9. **catalog-service**: Quản lý danh mục nội dung/sản phẩm (FastAPI)
10. **comment-rate-service**: Quản lý bình luận và đánh giá sách (FastAPI)
11. **recommender-ai-service**: Gợi ý sách theo heuristic AI (FastAPI)
12. **api-gateway**: Cổng giao tiếp và giao diện người dùng (FastAPI)

## Functional Requirements
- Customer registration automatically creates a cart
- Staff manages books
- Customer adds books to cart, view cart, update cart
- Order triggers payment and shipping
- Customer can rate books via comment-rate-service
- Home page supports personalized recommendations via recommender-ai-service

## Technical Stack
- Django REST Framework
- FastAPI
- Docker & Docker Compose
- MySQL (single instance with multiple databases)
- REST inter-service calls

## Project Structure
```
bookstore-micro05/
├── customer-service/
│   ├── app/
│   │   ├── models.py # Django app
│   │   ├── serializers.py
│   │   ├── urls.py
│   │   └── tests.py
│   ├── customer_service/
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── wsgi.py
│   │   └── asgi.py
│   ├── manage.py
│   ├── Dockerfile
│   └── requirements.txt
├── cart-service/
├── order-service/ # FastAPI app
├── payment-service/ # FastAPI app
├── shipping-service/ # FastAPI app
├── manager-service/ # FastAPI app
├── catalog-service/ # FastAPI app
├── comment-rate-service/ # FastAPI app
├── recommender-ai-service/ # FastAPI app
├── api-gateway/ # FastAPI app
├── book-service/
├── staff-service/
├── docker-compose.yml
└── .gitignore
```

## Prerequisites
- Docker Desktop installed and running
- Windows 10/11 or Linux/macOS

## Installation & Running

### 1. Navigate to project directory
```bash
cd d:\bookstore-micro05
```

### 2. Build and start all services
```bash
docker-compose up --build
```

This will:
- Create 4 PostgreSQL databases (one per service)
- Build Docker images for each service
- Run migrations
- Start all services

### 3. Access the APIs

Once running, you can access:
- **Customer Service**: http://localhost:8001/api/customers/
- **Cart Service**: http://localhost:8002/api/carts/
- **Book Service**: http://localhost:8003/api/books/
- **Staff Service**: http://localhost:8004/api/staff/
- **Order Service**: http://localhost:8005/docs
- **Payment Service**: http://localhost:8006/docs
- **Shipping Service**: http://localhost:8007/docs
- **Manager Service**: http://localhost:8008/docs
- **Catalog Service**: http://localhost:8009/docs
- **Comment Rate Service**: http://localhost:8010/docs
- **Recommender AI Service**: http://localhost:8011/docs
- **API Gateway UI**: http://localhost:8080/

### 4. Example API Calls

**Create a customer** (automatically creates a cart):
```bash
curl -X POST http://localhost:8001/api/customers/ \
  -H "Content-Type: application/json" \
  -d '{"name": "John Doe", "email": "john@example.com"}'
```

**Create a book** (staff-service):
```bash
curl -X POST http://localhost:8003/api/books/ \
  -H "Content-Type: application/json" \
  -d '{"title": "Django Book", "author": "Expert", "price": 49.99, "stock": 100}'
```

**Add item to cart**:
```bash
curl -X POST http://localhost:8002/api/carts/1/ \
  -H "Content-Type: application/json" \
  -d '{"book_id": 1, "quantity": 2}'
```

### 5. Stopping Services
```bash
docker-compose down
```

## Environment Variables
Each service uses the following environment variables (configured in docker-compose.yml):
- `DEBUG`: Set to 'True' for development
- `ALLOWED_HOSTS`: Comma-separated list of allowed hosts
- `DB_ENGINE`: Database engine (django.db.backends.postgresql)
- `DB_NAME`: Database name
- `DB_USER`: Database user (postgres)
- `DB_PASSWORD`: Database password
- `DB_HOST`: Database hostname
- `DB_PORT`: Database port

## Database Schema

### Customer Service
- **Customer**: id, name, email

### Cart Service
- **Cart**: id, customer_id
- **CartItem**: id, cart_id, book_id, quantity

### Book Service
- **Book**: id, title, author, price, description, stock

### Staff Service
- **Staff**: id, name, email, role, is_active

## Troubleshooting

### Services won't start
1. Ensure Docker is running: `docker info`
2. Check ports are available: 8001-8004, 5432-5435
3. View logs: `docker-compose logs [service-name]`

### Database connection errors
1. Wait for databases to initialize (20-30 seconds on first run)
2. Check PostgreSQL containers: `docker ps`
3. Verify environment variables in docker-compose.yml

### Port conflicts
If ports are already in use, update docker-compose.yml:
```yaml
ports:
  - "8005:8000"  # Change 8005 to available port
```

## Future Enhancements
- Implement authentication/authorization
- Persist manager/catalog/comment-rate/recommender data to MySQL
- Integrate recommender-ai-service with real user interaction data
- Implement inter-service communication patterns
- Add message queues (RabbitMQ/Kafka)
- Implement caching (Redis)
- Add monitoring and logging (ELK/Prometheus)

## Development Notes
- Each service has its own database to maintain independence
- REST calls between services use service names (e.g., `http://cart-service:8000`)
- Migrations are run automatically when services start
- Tests can be run with: `docker-compose exec [service-name] python manage.py test`
- manager-service, catalog-service, comment-rate-service, recommender-ai-service now persist data in MySQL using SQLAlchemy.
