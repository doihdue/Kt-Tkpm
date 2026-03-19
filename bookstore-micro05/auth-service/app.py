import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import jwt
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

app = FastAPI(title="Auth Service")

CUSTOMER_SERVICE_URL = os.getenv("CUSTOMER_SERVICE_URL", "http://customer-service:8000")
STAFF_SERVICE_URL = os.getenv("STAFF_SERVICE_URL", "http://staff-service:8000")
JWT_SECRET = os.getenv("JWT_SECRET", "bookstore_dev_secret")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "120"))


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


def normalize_staff_role(raw_role: Optional[str]) -> str:
    if raw_role in ("manager", "admin"):
        return "manager"
    return "staff"


def create_access_token(user_id: int, username: str, role: str) -> tuple[str, int]:
    expires_delta = timedelta(minutes=JWT_EXPIRE_MINUTES)
    expire_at = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int(expire_at.timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, int(expires_delta.total_seconds())


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {
            "id": int(payload.get("sub")),
            "username": payload.get("username"),
            "role": payload.get("role"),
            "exp": payload.get("exp"),
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token đã hết hạn")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token không hợp lệ")


@app.post("/auth/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    login_payload = {"username": payload.username, "password": payload.password}

    # staff/manager first
    try:
        async with httpx.AsyncClient(base_url=STAFF_SERVICE_URL, timeout=8) as client:
            response = await client.post("/api/auth/token/", json=login_payload)
        if response.status_code == 200:
            staff = response.json()
            role = normalize_staff_role(staff.get("role"))
            token, expires_in = create_access_token(staff.get("id"), staff.get("username"), role)
            return TokenResponse(
                access_token=token,
                expires_in=expires_in,
                user={"id": staff.get("id"), "username": staff.get("username"), "role": role},
            )
    except httpx.RequestError:
        pass

    # customer
    try:
        async with httpx.AsyncClient(base_url=CUSTOMER_SERVICE_URL, timeout=8) as client:
            response = await client.post("/api/auth/token/", json=login_payload)
        if response.status_code == 200:
            customer = response.json()
            token, expires_in = create_access_token(customer.get("id"), customer.get("username"), "customer")
            return TokenResponse(
                access_token=token,
                expires_in=expires_in,
                user={"id": customer.get("id"), "username": customer.get("username"), "role": "customer"},
            )
    except httpx.RequestError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth dependencies unavailable")

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sai tài khoản hoặc mật khẩu")


@app.get("/auth/validate")
async def validate(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Thiếu Bearer token")
    token = authorization.split(" ", 1)[1].strip()
    user = decode_token(token)
    return {"valid": True, "user": user}


@app.get("/auth/health")
def health():
    return {"service": "auth-service", "status": "ok"}
