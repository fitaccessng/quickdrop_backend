from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.orders import router as orders_router
from app.api.products import router as products_router
from app.api.rides import router as rides_router
from app.api.users import router as users_router
from app.api.vendors import router as vendors_router
from app.core.config import settings
import app.db.base  # noqa: F401
from app.db.session import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(vendors_router)
app.include_router(products_router)
app.include_router(orders_router)
app.include_router(rides_router)
app.include_router(users_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
