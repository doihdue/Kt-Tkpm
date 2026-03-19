import json
import os
import threading
import time
from uuid import uuid4

import pika
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Payment Service")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F")
EVENT_EXCHANGE = os.getenv("EVENT_EXCHANGE", "bookstore.events")

PAYMENTS = {}


class PaymentRequest(BaseModel):
    order_id: str
    amount: float
    method: str


def rabbit_params() -> pika.URLParameters:
    return pika.URLParameters(RABBITMQ_URL)


def publish_event(event_type: str, payload: dict):
    try:
        connection = pika.BlockingConnection(rabbit_params())
        channel = connection.channel()
        channel.exchange_declare(exchange=EVENT_EXCHANGE, exchange_type="fanout", durable=True)
        channel.basic_publish(exchange=EVENT_EXCHANGE, routing_key="", body=json.dumps({"event": event_type, "payload": payload}))
        connection.close()
    except Exception as exc:
        print(f"[payment-service] event publish failed: {exc}")


def reserve_payment(order_id: str, amount: float, method: str, simulate_failure: bool = False) -> dict:
    if simulate_failure:
        publish_event("payment.reserve_failed", {"order_id": order_id, "reason": "simulated"})
        return {"ok": False, "error": "Simulated payment failure"}

    payment_id = str(uuid4())
    PAYMENTS[payment_id] = {
        "order_id": order_id,
        "amount": amount,
        "method": method,
        "status": "reserved",
    }
    publish_event("payment.reserved", {"order_id": order_id, "payment_id": payment_id})
    return {"ok": True, "payment_id": payment_id, "status": "reserved"}


def compensate_payment(order_id: str, payment_id: str) -> dict:
    if payment_id in PAYMENTS:
        PAYMENTS[payment_id]["status"] = "cancelled"
        publish_event("payment.cancelled", {"order_id": order_id, "payment_id": payment_id})
        return {"ok": True, "payment_id": payment_id, "status": "cancelled"}
    return {"ok": True, "payment_id": payment_id, "status": "not_found"}


def rpc_worker_loop():
    while True:
        try:
            connection = pika.BlockingConnection(rabbit_params())
            channel = connection.channel()
            channel.queue_declare(queue="payment.reserve", durable=True)
            channel.queue_declare(queue="payment.compensate", durable=True)

            def on_request(ch, method, props, body):
                payload = json.loads(body.decode("utf-8"))

                if method.routing_key == "payment.reserve":
                    response = reserve_payment(
                        order_id=payload.get("order_id"),
                        amount=float(payload.get("amount") or 0),
                        method=payload.get("method") or "unknown",
                        simulate_failure=bool(payload.get("simulate_failure")),
                    )
                elif method.routing_key == "payment.compensate":
                    response = compensate_payment(
                        order_id=payload.get("order_id"),
                        payment_id=payload.get("payment_id"),
                    )
                else:
                    response = {"ok": False, "error": "Unknown routing key"}

                ch.basic_publish(
                    exchange="",
                    routing_key=props.reply_to,
                    properties=pika.BasicProperties(correlation_id=props.correlation_id),
                    body=json.dumps(response),
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue="payment.reserve", on_message_callback=on_request)
            channel.basic_consume(queue="payment.compensate", on_message_callback=on_request)
            print("[payment-service] RPC worker started")
            channel.start_consuming()
        except Exception as exc:
            print(f"[payment-service] RPC worker error: {exc}")
            time.sleep(3)


@app.on_event("startup")
def startup_event():
    worker = threading.Thread(target=rpc_worker_loop, daemon=True)
    worker.start()


@app.post("/payments")
def process_payment(req: PaymentRequest):
    result = reserve_payment(req.order_id, req.amount, req.method)
    if result.get("ok"):
        return {"payment_id": result.get("payment_id"), "status": "success", "order_id": req.order_id}
    return {"status": "failed", "order_id": req.order_id, "error": result.get("error")}


@app.post("/payments/{payment_id}/cancel")
def cancel_payment(payment_id: str):
    result = compensate_payment(order_id="manual", payment_id=payment_id)
    return result


@app.get("/payments/health")
def health():
    return {"service": "payment-service", "status": "ok"}
