from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import uuid4
import httpx
import os
import secrets
import string
import json

from sqlalchemy import create_engine, Column, String, Float, Text, Integer, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

app = FastAPI(title="Order Service")

PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8000")
SHIPPING_SERVICE_URL = os.getenv("SHIPPING_SERVICE_URL", "http://shipping-service:8000")
DB_URL = os.getenv("DB_URL", "mysql+pymysql://root:123456@db:3306/order_db")

engine = create_engine(DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class OrderRow(Base):
    __tablename__ = "orders"
    id = Column(String(36), primary_key=True)
    order_code = Column(String(20), unique=True, nullable=False)
    customer_id = Column(Integer, nullable=False)
    items = Column(Text, nullable=False)  # JSON
    total_price = Column(Float, default=0.0)
    status = Column(String(50), default="pending")
    payment_method = Column(String(50), nullable=True)
    shipping_address = Column(Text, nullable=True)
    payment_id = Column(String(100), nullable=True)
    shipping_id = Column(String(100), nullable=True)


Base.metadata.create_all(bind=engine)


def ensure_orders_schema():
    """
    Keep compatibility with old order_db schemas that may have an outdated
    `orders` table without newer columns (e.g., `items`).
    """
    inspector = inspect(engine)
    if not inspector.has_table("orders"):
        return

    column_defs = {col["name"]: col for col in inspector.get_columns("orders")}
    existing_columns = set(column_defs.keys())
    required_columns = {
        "order_code": "VARCHAR(20)",
        "items": "TEXT",
        "total_price": "FLOAT",
        "status": "VARCHAR(50)",
        "payment_method": "VARCHAR(50)",
        "shipping_address": "TEXT",
        "payment_id": "VARCHAR(100)",
        "shipping_id": "VARCHAR(100)",
    }

    with engine.begin() as conn:
        # Legacy schemas may define `id` as INT. Convert to UUID-friendly text.
        if "id" in column_defs:
            id_type = str(column_defs["id"].get("type", "")).lower()
            if "char" not in id_type and "text" not in id_type:
                try:
                    conn.execute(text("ALTER TABLE orders MODIFY COLUMN id VARCHAR(36) NOT NULL"))
                except Exception as exc:
                    err = str(exc).lower()
                    if "incompatible" in err or "order_items_ibfk_1" in err:
                        # Legacy schema: order_items references orders.id as INT.
                        # This service no longer uses order_items, so drop it to unblock migration.
                        conn.execute(text("DROP TABLE IF EXISTS order_items"))
                        conn.execute(text("ALTER TABLE orders MODIFY COLUMN id VARCHAR(36) NOT NULL"))
                    else:
                        raise

        for col_name, col_type in required_columns.items():
            if col_name not in existing_columns:
                conn.execute(text(f"ALTER TABLE orders ADD COLUMN {col_name} {col_type} NULL"))

        # Backfill safe defaults for legacy rows to avoid null parsing errors.
        if "items" in required_columns:
            conn.execute(text("UPDATE orders SET items = '[]' WHERE items IS NULL"))
        if "status" in required_columns:
            conn.execute(text("UPDATE orders SET status = 'pending' WHERE status IS NULL OR status = ''"))
        if "total_price" in required_columns:
            conn.execute(text("UPDATE orders SET total_price = 0 WHERE total_price IS NULL"))


ensure_orders_schema()


def generate_order_code(length=8):
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


class OrderItem(BaseModel):
    book_id: int
    quantity: int
    price_at_purchase: float
    book_title: str


class Order(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    order_code: str = Field(default_factory=generate_order_code)
    customer_id: int
    items: List[OrderItem]
    total_price: float = 0.0
    status: str = "pending"
    payment_method: Optional[str] = None
    shipping_address: Optional[str] = None
    payment_id: Optional[str] = None
    shipping_id: Optional[str] = None


def row_to_order(row: OrderRow) -> Order:
    return Order(
        id=row.id,
        order_code=row.order_code,
        customer_id=row.customer_id,
        items=json.loads(row.items or "[]"),
        total_price=row.total_price,
        status=row.status,
        payment_method=row.payment_method,
        shipping_address=row.shipping_address,
        payment_id=row.payment_id,
        shipping_id=row.shipping_id,
    )


def _db_update(order_id: str, **kwargs):
    db: Session = SessionLocal()
    try:
        row = db.query(OrderRow).filter(OrderRow.id == order_id).first()
        if row:
            for key, val in kwargs.items():
                setattr(row, key, val)
            db.commit()
    finally:
        db.close()


@app.get("/api/orders", response_model=List[Order])
def list_orders(customer_id: Optional[int] = None):
    db: Session = SessionLocal()
    try:
        q = db.query(OrderRow)
        if customer_id:
            q = q.filter(OrderRow.customer_id == customer_id)
        return [row_to_order(r) for r in q.all()]
    finally:
        db.close()


@app.post("/api/orders", response_model=Order, status_code=201)
async def create_order(order: Order):
    db: Session = SessionLocal()
    try:
        if db.query(OrderRow).filter(OrderRow.id == order.id).first():
            raise HTTPException(status_code=400, detail="Order already exists")
        row = OrderRow(
            id=order.id,
            order_code=order.order_code,
            customer_id=order.customer_id,
            items=json.dumps([item.model_dump() for item in order.items]),
            total_price=order.total_price,
            status=order.status,
            payment_method=order.payment_method,
            shipping_address=order.shipping_address,
            payment_id=order.payment_id,
            shipping_id=order.shipping_id,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()

    initial_status = order.status

    async with httpx.AsyncClient(timeout=10) as client:
        if order.payment_method and order.payment_method != "cod":
            try:
                payment_res = await client.post(
                    f"{PAYMENT_SERVICE_URL}/payments",
                    json={"order_id": order.id, "amount": order.total_price, "method": order.payment_method},
                )
                payment_res.raise_for_status()
                order.payment_id = payment_res.json().get("payment_id")
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                _db_update(order.id, status="payment_failed")
                raise HTTPException(status_code=503, detail=f"Payment service failed: {e}")

        if order.shipping_address:
            try:
                ship_res = await client.post(
                    f"{SHIPPING_SERVICE_URL}/shipments",
                    json={"order_id": order.id, "address": order.shipping_address},
                )
                ship_res.raise_for_status()
                order.shipping_id = ship_res.json().get("shipping_id")
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                _db_update(order.id, status="shipping_failed")
                raise HTTPException(status_code=503, detail=f"Shipping service failed: {e}")

    _db_update(order.id,
               status=initial_status,
               payment_id=order.payment_id,
               shipping_id=order.shipping_id)
    order.status = initial_status
    return order


@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    db: Session = SessionLocal()
    try:
        row = db.query(OrderRow).filter(OrderRow.id == order_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        return row_to_order(row)
    finally:
        db.close()


@app.patch("/api/orders/{order_id}/status", response_model=Order)
def update_order_status(order_id: str, status: str):
    db: Session = SessionLocal()
    try:
        row = db.query(OrderRow).filter(OrderRow.id == order_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        row.status = status
        db.commit()
        db.refresh(row)
        return row_to_order(row)
    finally:
        db.close()
