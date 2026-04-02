import json
import os
import secrets
import string
import threading
import time
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

import pika
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

app = FastAPI(title="Order Service")

DB_URL = os.getenv("DB_URL", "mysql+pymysql://root:123456@db:3306/order_db")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F")
EVENT_EXCHANGE = os.getenv("EVENT_EXCHANGE", "bookstore.events")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "bookstore.events")
OUTBOX_POLL_SECONDS = float(os.getenv("OUTBOX_POLL_SECONDS", "2"))
OUTBOX_BATCH_SIZE = int(os.getenv("OUTBOX_BATCH_SIZE", "50"))
OUTBOX_MAX_RETRIES = int(os.getenv("OUTBOX_MAX_RETRIES", "20"))

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


class OutboxEventRow(Base):
    __tablename__ = "order_outbox"

    id = Column(Integer, primary_key=True, autoincrement=True)
    aggregate_type = Column(String(50), nullable=False, index=True)
    aggregate_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    payload = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)


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


def _publish_rabbit(event_type: str, payload: dict):
    try:
        connection = pika.BlockingConnection(rabbit_params())
        channel = connection.channel()
        channel.exchange_declare(exchange=EVENT_EXCHANGE, exchange_type="fanout", durable=True)
        message = json.dumps({"event": event_type, "payload": payload})
        channel.basic_publish(exchange=EVENT_EXCHANGE, routing_key="", body=message)
        connection.close()
        return True, None
    except Exception as exc:
        return False, str(exc)


def _publish_kafka(event_type: str, payload: dict):
    try:
        from kafka import KafkaProducer

        producer = KafkaProducer(
            bootstrap_servers=[server.strip() for server in KAFKA_BOOTSTRAP_SERVERS.split(",") if server.strip()],
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda v: v.encode("utf-8") if v else None,
        )
        producer.send(
            KAFKA_TOPIC,
            key=event_type,
            value={"event": event_type, "payload": payload},
        )
        producer.flush(timeout=5)
        producer.close()
        return True, None
    except Exception as exc:
        return False, str(exc)


def publish_event(event_type: str, payload: dict):
    rabbit_ok, rabbit_err = _publish_rabbit(event_type, payload)
    kafka_ok, kafka_err = _publish_kafka(event_type, payload)

    if rabbit_ok and kafka_ok:
        return True, None

    errors = []
    if not rabbit_ok:
        errors.append(f"rabbit: {rabbit_err}")
    if not kafka_ok:
        errors.append(f"kafka: {kafka_err}")
    return False, "; ".join(errors)


def _append_outbox_event(
    db: Session,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict,
):
    db.add(
        OutboxEventRow(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=json.dumps(payload),
            status="pending",
            retry_count=0,
        )
    )


def enqueue_outbox_event(aggregate_type: str, aggregate_id: str, event_type: str, payload: dict):
    db: Session = SessionLocal()
    try:
        _append_outbox_event(db, aggregate_type, aggregate_id, event_type, payload)
        db.commit()
    finally:
        db.close()


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


def _db_update(order_id: str, event_type: Optional[str] = None, event_payload: Optional[dict] = None, **kwargs):
    db: Session = SessionLocal()
    try:
        row = db.query(OrderRow).filter(OrderRow.id == order_id).first()
        if row:
            for key, val in kwargs.items():
                setattr(row, key, val)
            if event_type and event_payload is not None:
                _append_outbox_event(db, "order", order_id, event_type, event_payload)
            db.commit()
    finally:
        db.close()


def dispatch_outbox_once():
    db: Session = SessionLocal()
    try:
        events = (
            db.query(OutboxEventRow)
            .filter(OutboxEventRow.status.in_(["pending", "failed"]))
            .filter(OutboxEventRow.retry_count < OUTBOX_MAX_RETRIES)
            .order_by(OutboxEventRow.id.asc())
            .limit(OUTBOX_BATCH_SIZE)
            .all()
        )

        for event in events:
            try:
                payload = json.loads(event.payload or "{}")
            except (TypeError, ValueError):
                payload = {}

            ok, err = publish_event(event.event_type, payload)
            if ok:
                event.status = "published"
                event.published_at = datetime.utcnow()
                event.last_error = None
            else:
                event.status = "failed"
                event.retry_count = (event.retry_count or 0) + 1
                event.last_error = (err or "publish failed")[:2000]

        db.commit()
    finally:
        db.close()


def outbox_dispatch_loop():
    while True:
        try:
            dispatch_outbox_once()
        except Exception as exc:
            print(f"[order-service] outbox dispatcher error: {exc}")
        time.sleep(OUTBOX_POLL_SECONDS)


@app.on_event("startup")
def startup_event():
    worker = threading.Thread(target=outbox_dispatch_loop, daemon=True)
    worker.start()


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
        _append_outbox_event(
            db,
            "order",
            order.id,
            "order.pending",
            {"order_id": order.id, "order_code": order.order_code},
        )
        db.commit()
    finally:
        db.close()

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
            _db_update(
                order.id,
                status="payment_failed",
                event_type="order.payment_failed",
                event_payload={"order_id": order.id, "detail": payment_resp.get("error")},
            )
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
            _db_update(
                order.id,
                status="shipping_failed",
                payment_id=payment_id,
                event_type="order.shipping_failed",
                event_payload={"order_id": order.id, "detail": shipping_resp.get("error")},
            )
            compensate(payment_id=payment_id, shipping_id=None, order_id=order.id)
            _db_update(
                order.id,
                status="compensated",
                event_type="order.compensated",
                event_payload={"order_id": order.id, "reason": "shipping_failed"},
            )
            raise HTTPException(status_code=503, detail=f"Shipping reserve failed: {shipping_resp.get('error')}")
        shipping_id = shipping_resp.get("shipping_id")

        if order.simulate_confirm_failure:
            raise RuntimeError("Simulated confirm failure")

        final_status = order.status or "processing"
        _db_update(
            order.id,
            status=final_status,
            payment_id=payment_id,
            shipping_id=shipping_id,
            event_type="order.confirmed",
            event_payload={"order_id": order.id, "order_code": order.order_code, "status": final_status},
        )

        order.status = final_status
        order.payment_id = payment_id
        order.shipping_id = shipping_id
        return order

    except HTTPException:
        raise
    except Exception as exc:
        _db_update(
            order.id,
            status="confirm_failed",
            payment_id=payment_id,
            shipping_id=shipping_id,
            event_type="order.confirm_failed",
            event_payload={"order_id": order.id, "detail": str(exc)},
        )
        compensate(payment_id=payment_id, shipping_id=shipping_id, order_id=order.id)
        _db_update(
            order.id,
            status="compensated",
            event_type="order.compensated",
            event_payload={"order_id": order.id, "reason": "confirm_failed"},
        )
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
