import json
import os
import secrets
import string
from typing import List, Optional
from uuid import uuid4

import pika
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, Float, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

app = FastAPI(title="Order Service")

DB_URL = os.getenv("DB_URL", "mysql+pymysql://root:123456@db:3306/order_db")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F")
EVENT_EXCHANGE = os.getenv("EVENT_EXCHANGE", "bookstore.events")

engine = create_engine(DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class OrderRow(Base):
    __tablename__ = "orders"
    id = Column(String(36), primary_key=True)
    order_code = Column(String(20), unique=True, nullable=False)
    customer_id = Column(Integer, nullable=False)
    items = Column(Text, nullable=False)
    total_price = Column(Float, default=0.0)
    status = Column(String(50), default="pending")
    payment_method = Column(String(50), nullable=True)
    shipping_address = Column(Text, nullable=True)
    payment_id = Column(String(100), nullable=True)
    shipping_id = Column(String(100), nullable=True)


Base.metadata.create_all(bind=engine)


def ensure_orders_schema():
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
        if "id" in column_defs:
            id_type = str(column_defs["id"].get("type", "")).lower()
            if "char" not in id_type and "text" not in id_type:
                try:
                    conn.execute(text("ALTER TABLE orders MODIFY COLUMN id VARCHAR(36) NOT NULL"))
                except Exception as exc:
                    err = str(exc).lower()
                    if "incompatible" in err or "order_items_ibfk_1" in err:
                        conn.execute(text("DROP TABLE IF EXISTS order_items"))
                        conn.execute(text("ALTER TABLE orders MODIFY COLUMN id VARCHAR(36) NOT NULL"))
                    else:
                        raise

        for col_name, col_type in required_columns.items():
            if col_name not in existing_columns:
                conn.execute(text(f"ALTER TABLE orders ADD COLUMN {col_name} {col_type} NULL"))

        conn.execute(text("UPDATE orders SET items = '[]' WHERE items IS NULL"))
        conn.execute(text("UPDATE orders SET status = 'pending' WHERE status IS NULL OR status = ''"))
        conn.execute(text("UPDATE orders SET total_price = 0 WHERE total_price IS NULL"))


ensure_orders_schema()


def rabbit_params() -> pika.URLParameters:
    return pika.URLParameters(RABBITMQ_URL)


def publish_event(event_type: str, payload: dict):
    try:
        connection = pika.BlockingConnection(rabbit_params())
        channel = connection.channel()
        channel.exchange_declare(exchange=EVENT_EXCHANGE, exchange_type="fanout", durable=True)
        message = json.dumps({"event": event_type, "payload": payload})
        channel.basic_publish(exchange=EVENT_EXCHANGE, routing_key="", body=message)
        connection.close()
    except Exception as exc:
        print(f"[order-service] event publish failed: {exc}")


def rpc_call(queue_name: str, payload: dict, timeout_seconds: int = 12) -> dict:
    connection = pika.BlockingConnection(rabbit_params())
    channel = connection.channel()
    channel.queue_declare(queue=queue_name, durable=True)

    callback_queue = channel.queue_declare(queue="", exclusive=True).method.queue
    correlation_id = str(uuid4())
    response_body = None

    def on_response(ch, method, props, body):
        nonlocal response_body
        if props.correlation_id == correlation_id:
            response_body = body

    channel.basic_consume(queue=callback_queue, on_message_callback=on_response, auto_ack=True)
    channel.basic_publish(
        exchange="",
        routing_key=queue_name,
        properties=pika.BasicProperties(
            reply_to=callback_queue,
            correlation_id=correlation_id,
            delivery_mode=2,
        ),
        body=json.dumps(payload),
    )

    elapsed = 0
    while response_body is None and elapsed < timeout_seconds:
        connection.process_data_events(time_limit=1)
        elapsed += 1

    connection.close()

    if response_body is None:
        raise HTTPException(status_code=503, detail=f"RPC timeout for queue {queue_name}")

    decoded = json.loads(response_body.decode("utf-8"))
    return decoded


def generate_order_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


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

    simulate_payment_failure: bool = False
    simulate_shipping_failure: bool = False
    simulate_confirm_failure: bool = False


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


def compensate(payment_id: Optional[str], shipping_id: Optional[str], order_id: str):
    if shipping_id:
        try:
            rpc_call("shipping.compensate", {"order_id": order_id, "shipping_id": shipping_id})
        except Exception as exc:
            print(f"[order-service] shipping compensation failed: {exc}")

    if payment_id:
        try:
            rpc_call("payment.compensate", {"order_id": order_id, "payment_id": payment_id})
        except Exception as exc:
            print(f"[order-service] payment compensation failed: {exc}")


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
def create_order(order: Order):
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
            status="pending",
            payment_method=order.payment_method,
            shipping_address=order.shipping_address,
            payment_id=None,
            shipping_id=None,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()

    publish_event("order.pending", {"order_id": order.id, "order_code": order.order_code})

    payment_id = None
    shipping_id = None

    try:
        payment_resp = rpc_call(
            "payment.reserve",
            {
                "order_id": order.id,
                "amount": order.total_price,
                "method": order.payment_method or "cod",
                "simulate_failure": order.simulate_payment_failure,
            },
        )
        if not payment_resp.get("ok"):
            _db_update(order.id, status="payment_failed")
            publish_event("order.payment_failed", {"order_id": order.id, "detail": payment_resp.get("error")})
            raise HTTPException(status_code=503, detail=f"Payment reserve failed: {payment_resp.get('error')}")
        payment_id = payment_resp.get("payment_id")

        shipping_resp = rpc_call(
            "shipping.reserve",
            {
                "order_id": order.id,
                "address": order.shipping_address,
                "simulate_failure": order.simulate_shipping_failure,
            },
        )
        if not shipping_resp.get("ok"):
            _db_update(order.id, status="shipping_failed", payment_id=payment_id)
            publish_event("order.shipping_failed", {"order_id": order.id, "detail": shipping_resp.get("error")})
            compensate(payment_id=payment_id, shipping_id=None, order_id=order.id)
            _db_update(order.id, status="compensated")
            publish_event("order.compensated", {"order_id": order.id, "reason": "shipping_failed"})
            raise HTTPException(status_code=503, detail=f"Shipping reserve failed: {shipping_resp.get('error')}")
        shipping_id = shipping_resp.get("shipping_id")

        if order.simulate_confirm_failure:
            raise RuntimeError("Simulated confirm failure")

        final_status = order.status or "processing"
        _db_update(order.id, status=final_status, payment_id=payment_id, shipping_id=shipping_id)
        publish_event("order.confirmed", {"order_id": order.id, "order_code": order.order_code, "status": final_status})

        order.status = final_status
        order.payment_id = payment_id
        order.shipping_id = shipping_id
        return order

    except HTTPException:
        raise
    except Exception as exc:
        _db_update(order.id, status="confirm_failed", payment_id=payment_id, shipping_id=shipping_id)
        publish_event("order.confirm_failed", {"order_id": order.id, "detail": str(exc)})
        compensate(payment_id=payment_id, shipping_id=shipping_id, order_id=order.id)
        _db_update(order.id, status="compensated")
        publish_event("order.compensated", {"order_id": order.id, "reason": "confirm_failed"})
        raise HTTPException(status_code=503, detail="Order saga failed and was compensated")


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


@app.get("/health")
def health():
    return {"service": "order-service", "status": "ok"}
