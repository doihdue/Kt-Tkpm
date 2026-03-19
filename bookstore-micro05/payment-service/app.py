from fastapi import FastAPI
from pydantic import BaseModel
from uuid import uuid4

app = FastAPI(title="Payment Service")

class PaymentRequest(BaseModel):
    order_id: str
    amount: float
    method: str

@app.post("/payments")
def process_payment(req: PaymentRequest):
    # Mock payment processing
    return {"payment_id": str(uuid4()), "status": "success", "order_id": req.order_id}