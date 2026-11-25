from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import CaptureRun, Site
from ..services.pipeline_service import (
    execute_capture_and_extract_pipeline,
    serialize_capture_record,
)

router = APIRouter(prefix="/api/capture", tags=["capture"])

class CaptureRequest(BaseModel):
    url: HttpUrl
    site_id: int | None = None

@router.post("", status_code=201)
async def capture(payload: CaptureRequest, db: Session = Depends(get_db)):
    site = None
    if payload.site_id is not None:
        site = db.get(Site, payload.site_id)
        if not site:
            raise HTTPException(404, "Website not found.")
        if str(payload.url).rstrip("/") != site.url.rstrip("/"):
            raise HTTPException(400, "Capture URL must match the registered website URL.")
    try:
        result = await execute_capture_and_extract_pipeline(
            url=str(payload.url),
            site_id=payload.site_id,
            db=db,
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        import traceback
        db.rollback()
        traceback.print_exc()

        error_message = (
            f"Capture failed ({type(exc).__name__}): {repr(exc)}"
        )
        raise HTTPException(500, error_message) from exc

@router.get("/history")
def capture_history(site_id: int | None = Query(default=None), limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    stmt = select(CaptureRun).order_by(CaptureRun.created_at.desc()).limit(limit)
    if site_id is not None:
        stmt = select(CaptureRun).where(CaptureRun.site_id == site_id).order_by(CaptureRun.created_at.desc()).limit(limit)
    return [serialize_capture_record(item) for item in db.scalars(stmt).all()]

@router.get("/{capture_id}")
def get_capture(capture_id: int, db: Session = Depends(get_db)):
    item = db.get(CaptureRun, capture_id)
    if not item:
        raise HTTPException(404, "Capture record not found.")
    return serialize_capture_record(item)

@router.get("/{capture_id}/screenshot")
def get_capture_screenshot(capture_id: int, db: Session = Depends(get_db)):
    item = db.get(CaptureRun, capture_id)
    if not item or not item.screenshot_path:
        raise HTTPException(404, "Screenshot not found for this capture.")

    path = Path(item.screenshot_path)
    if not path.is_file():
        raise HTTPException(404, "Screenshot file does not exist on disk.")

    return FileResponse(path, media_type="image/png")

@router.get("/{capture_id}/html")
def get_capture_html(capture_id: int, db: Session = Depends(get_db)):
    item = db.get(CaptureRun, capture_id)
    if not item or not item.screenshot_path:
        raise HTTPException(404, "Capture data not found.")

    raw_path = Path(item.screenshot_path).parent / "raw.html"
    if raw_path.is_file():
        content = raw_path.read_text(encoding="utf-8", errors="replace")
        return HTMLResponse(content)

    return HTMLResponse(item.cleaned_html_preview)
