from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, me, devices
from app.core.config import get_settings
from app.db.session import get_engine

settings = get_settings()  # only used to configure the app object itself


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await get_engine().dispose()  # creating the engine is lazy; no connection is opened


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(me.router)
api_v1.include_router(devices.router)
app.include_router(api_v1)
