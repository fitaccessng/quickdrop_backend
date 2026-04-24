import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.api.notifications import router as notifications_router
from app.api.orders import router as orders_router
from app.api.products import router as products_router
from app.api.rider import router as rider_router
from app.api.rides import router as rides_router
from app.api.system import router as system_router
from app.api.users import router as users_router
from app.api.vendors import router as vendors_router
from app.core.config import settings
import app.db.base  # noqa: F401
from app.db.session import Base, engine


SQLITE_MIGRATIONS = {
    "products": {
        "sku": "ALTER TABLE products ADD COLUMN sku VARCHAR(64)",
        "stock_quantity": "ALTER TABLE products ADD COLUMN stock_quantity INTEGER NOT NULL DEFAULT 0",
        "low_stock_threshold": "ALTER TABLE products ADD COLUMN low_stock_threshold INTEGER NOT NULL DEFAULT 5",
        "image_urls": "ALTER TABLE products ADD COLUMN image_urls JSON",
    },
    "users": {
        "is_onboarded": "ALTER TABLE users ADD COLUMN is_onboarded BOOLEAN NOT NULL DEFAULT 0",
        "avatar_url": "ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500)",
        "city": "ALTER TABLE users ADD COLUMN city VARCHAR(120)",
        "state": "ALTER TABLE users ADD COLUMN state VARCHAR(120)",
        "street": "ALTER TABLE users ADD COLUMN street VARCHAR(255)",
        "po_box": "ALTER TABLE users ADD COLUMN po_box VARCHAR(50)",
        "vehicle_type": "ALTER TABLE users ADD COLUMN vehicle_type VARCHAR(40)",
        "license_number": "ALTER TABLE users ADD COLUMN license_number VARCHAR(80)",
        "rider_status": "ALTER TABLE users ADD COLUMN rider_status VARCHAR(40) NOT NULL DEFAULT 'offline'",
        "wallet_balance": "ALTER TABLE users ADD COLUMN wallet_balance FLOAT NOT NULL DEFAULT 0",
        "total_earnings": "ALTER TABLE users ADD COLUMN total_earnings FLOAT NOT NULL DEFAULT 0",
        "total_deliveries": "ALTER TABLE users ADD COLUMN total_deliveries INTEGER NOT NULL DEFAULT 0",
        "current_latitude": "ALTER TABLE users ADD COLUMN current_latitude FLOAT",
        "current_longitude": "ALTER TABLE users ADD COLUMN current_longitude FLOAT",
    },
    "orders": {
        "rider_id": "ALTER TABLE orders ADD COLUMN rider_id INTEGER",
        "tracking_latitude": "ALTER TABLE orders ADD COLUMN tracking_latitude FLOAT",
        "tracking_longitude": "ALTER TABLE orders ADD COLUMN tracking_longitude FLOAT",
    },
    "payout_requests": {},
    "notifications": {},
    "vendors": {
        "street": "ALTER TABLE vendors ADD COLUMN street VARCHAR(255)",
        "po_box": "ALTER TABLE vendors ADD COLUMN po_box VARCHAR(50)",
        "latitude": "ALTER TABLE vendors ADD COLUMN latitude FLOAT",
        "longitude": "ALTER TABLE vendors ADD COLUMN longitude FLOAT",
        "is_approved": "ALTER TABLE vendors ADD COLUMN is_approved BOOLEAN NOT NULL DEFAULT 0",
        "business_registration_number": "ALTER TABLE vendors ADD COLUMN business_registration_number VARCHAR(120)",
        "vat_number": "ALTER TABLE vendors ADD COLUMN vat_number VARCHAR(60)",
        "south_african_id_number": "ALTER TABLE vendors ADD COLUMN south_african_id_number VARCHAR(30)",
        "bank_account_name": "ALTER TABLE vendors ADD COLUMN bank_account_name VARCHAR(120)",
        "delivery_radius_km": "ALTER TABLE vendors ADD COLUMN delivery_radius_km FLOAT NOT NULL DEFAULT 5",
        "auto_accept_orders": "ALTER TABLE vendors ADD COLUMN auto_accept_orders BOOLEAN NOT NULL DEFAULT 0",
        "notifications_enabled": "ALTER TABLE vendors ADD COLUMN notifications_enabled BOOLEAN NOT NULL DEFAULT 1",
        "support_email": "ALTER TABLE vendors ADD COLUMN support_email VARCHAR(255)",
        "support_phone": "ALTER TABLE vendors ADD COLUMN support_phone VARCHAR(30)",
    },
    "addresses": {
        "latitude": "ALTER TABLE addresses ADD COLUMN latitude FLOAT",
        "longitude": "ALTER TABLE addresses ADD COLUMN longitude FLOAT",
    },
    "service_categories": {},
    "delivery_settings": {},
}

logger = logging.getLogger("quickdrop.api")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

RATE_LIMIT_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 120
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLIENT_DIST_DIR = PROJECT_ROOT / "client" / "dist"
NON_SPA_PATHS = {
    "admin",
    "auth",
    "delivery-settings",
    "health",
    "notifications",
    "orders",
    "products",
    "request-rider",
    "rider",
    "rides",
    "service-categories",
    "user",
    "vendors",
}


def _ensure_sqlite_columns(conn) -> None:
    for table_name, columns in SQLITE_MIGRATIONS.items():
        existing = {
            row[1]
            for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, sql in columns.items():
            if column_name not in existing:
                conn.exec_driver_sql(sql)


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name() == "sqlite":
            await conn.run_sync(_ensure_sqlite_columns)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(self)"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    bucket_key = f"{client_ip}:{request.url.path}"
    now = time.time()
    bucket = RATE_LIMIT_BUCKETS[bucket_key]
    while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
        return JSONResponse(status_code=429, content={"detail": "Too many requests. Please slow down."})
    bucket.append(now)
    return await call_next(request)


@app.middleware("http")
async def error_logging_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        if response.status_code >= 400:
            logger.warning("%s %s -> %s", request.method, request.url.path, response.status_code)
        return response
    except Exception:
        logger.exception("Unhandled error while processing %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(vendors_router)
app.include_router(products_router)
app.include_router(orders_router)
app.include_router(rider_router)
app.include_router(rides_router)
app.include_router(users_router)
app.include_router(notifications_router)
app.include_router(system_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    if not CLIENT_DIST_DIR.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found")

    requested_path = (CLIENT_DIST_DIR / full_path).resolve()
    if requested_path.is_file() and CLIENT_DIST_DIR in requested_path.parents:
        return FileResponse(requested_path)

    first_segment = full_path.split("/", 1)[0]
    if first_segment in NON_SPA_PATHS:
        raise HTTPException(status_code=404, detail="Not found")

    return FileResponse(CLIENT_DIST_DIR / "index.html")
