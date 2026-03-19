import json
import os
import threading
import time
from uuid import uuid4

import pika
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Shipping Service")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F")
EVENT_EXCHANGE = os.getenv("EVENT_EXCHANGE", "bookstore.events")

SHIPMENTS = {}


class ShipmentRequest(BaseModel):
    order_id: str
    address: str


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
        print(f"[shipping-service] event publish failed: {exc}")


def reserve_shipping(order_id: str, address: str, simulate_failure: bool = False) -> dict:
    if simulate_failure:
        publish_event("shipping.reserve_failed", {"order_id": order_id, "reason": "simulated"})
        return {"ok": False, "error": "Simulated shipping failure"}

    shipping_id = str(uuid4())
    SHIPMENTS[shipping_id] = {
        "order_id": order_id,
        "address": address,
        "status": "reserved",
    }
    publish_event("shipping.reserved", {"order_id": order_id, "shipping_id": shipping_id})
    return {"ok": True, "shipping_id": shipping_id, "status": "reserved"}


def compensate_shipping(order_id: str, shipping_id: str) -> dict:
    if shipping_id in SHIPMENTS:
        SHIPMENTS[shipping_id]["status"] = "cancelled"
        publish_event("shipping.cancelled", {"order_id": order_id, "shipping_id": shipping_id})
        return {"ok": True, "shipping_id": shipping_id, "status": "cancelled"}
    return {"ok": True, "shipping_id": shipping_id, "status": "not_found"}


def rpc_worker_loop():
    while True:
        try:
            connection = pika.BlockingConnection(rabbit_params())
            channel = connection.channel()
            channel.queue_declare(queue="shipping.reserve", durable=True)
            channel.queue_declare(queue="shipping.compensate", durable=True)

            def on_request(ch, method, props, body):
                payload = json.loads(body.decode("utf-8"))

                if method.routing_key == "shipping.reserve":
                    response = reserve_shipping(
                        order_id=payload.get("order_id"),
                        address=payload.get("address") or "",
                        simulate_failure=bool(payload.get("simulate_failure")),
                    )
                elif method.routing_key == "shipping.compensate":
                    response = compensate_shipping(
                        order_id=payload.get("order_id"),
                        shipping_id=payload.get("shipping_id"),
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
            channel.basic_consume(queue="shipping.reserve", on_message_callback=on_request)
            channel.basic_consume(queue="shipping.compensate", on_message_callback=on_request)
            print("[shipping-service] RPC worker started")
            channel.start_consuming()
        except Exception as exc:
            print(f"[shipping-service] RPC worker error: {exc}")
            time.sleep(3)


@app.on_event("startup")
def startup_event():
    worker = threading.Thread(target=rpc_worker_loop, daemon=True)
    worker.start()


@app.post("/shipments")
def create_shipment(req: ShipmentRequest):
    result = reserve_shipping(req.order_id, req.address)
    if result.get("ok"):
        return {"shipping_id": result.get("shipping_id"), "status": "shipped", "order_id": req.order_id}
    return {"status": "failed", "order_id": req.order_id, "error": result.get("error")}


@app.post("/shipments/{shipping_id}/cancel")
def cancel_shipment(shipping_id: str):
    result = compensate_shipping(order_id="manual", shipping_id=shipping_id)
    return result


@app.get("/shipments/health")
def health():
    return {"service": "shipping-service", "status": "ok"}
