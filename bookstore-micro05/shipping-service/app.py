from fastapi import FastAPI
from pydantic import BaseModel
from uuid import uuid4

app = FastAPI(title="Shipping Service")

class ShipmentRequest(BaseModel):
    order_id: str
    address: str

@app.post("/shipments")
def create_shipment(req: ShipmentRequest):
    # Mock shipping creation
    return {"shipping_id": str(uuid4()), "status": "shipped", "order_id": req.order_id}