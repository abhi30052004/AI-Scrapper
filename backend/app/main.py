import sys
import asyncio

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .config import settings
from .db import Base, engine
from . import models
from .routers import sites, capture
from app.routers.onboarding import router as onboarding_router
from app.routers.extraction import router as extraction_router
from app.routers.change_detection import router as change_detection_router
from app.routers.self_healing import router as self_healing_router
from app.routers.database import router as database_router
from app.routers.products import router as products_router
from app.services.onboarding import initialize_onboarding_db
from app.services.extraction_service import initialize_extraction_db
from app.services.change_detection_service import initialize_change_detection_db
from app.services.database_explorer_service import initialize_database_explorer_db

Path("data/snapshots").mkdir(parents=True, exist_ok=True)
Base.metadata.create_all(bind=engine)
initialize_onboarding_db()
initialize_extraction_db()
initialize_change_detection_db()
initialize_database_explorer_db()
app = FastAPI(title=settings.app_name, version="0.2.0")
app.add_middleware(CORSMiddleware,
    allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/artifacts", StaticFiles(directory="data/snapshots"), name="artifacts")

app.include_router(sites.router)
app.include_router(capture.router)
app.include_router(onboarding_router)
app.include_router(extraction_router)
app.include_router(change_detection_router)
app.include_router(self_healing_router)
app.include_router(database_router)
app.include_router(products_router)

@app.get("/api/health")
def health():
    return {"status":"ok","service":settings.app_name,"database":"sqlite","capture_engine":"playwright"}
