from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import CaptureRun, Site
from ..config import settings
from ..services.capture import capture_page
from ..services.cleaner import clean_html

router = APIRouter(prefix="/api/capture", tags=["capture"])

class CaptureRequest(BaseModel):
    url: HttpUrl
    site_id: int | None = None

def serialize_capture(item: CaptureRun):
    screenshot_url = None
    if item.screenshot_path:
        path = Path(item.screenshot_path)
        screenshot_url = f"/artifacts/{path.parent.name}/{path.name}"
    return {
        "id": item.id, "site_id": item.site_id,
        "requested_url": item.requested_url, "final_url": item.final_url,
        "page_title": item.page_title, "status_code": item.status_code,
        "load_time_ms": item.load_time_ms, "html_characters": item.html_characters,
        "cleaned_html_characters": item.cleaned_html_characters,
        "screenshot_url": screenshot_url,
        "cleaned_html_preview": item.cleaned_html_preview,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }

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
        result = await capture_page(str(payload.url), "data/snapshots")
        cleaned = clean_html(result.html, max_chars=settings.max_html_chars)
        record = CaptureRun(
            site_id=site.id if site else None, requested_url=result.requested_url,
            final_url=result.final_url, page_title=result.page_title,
            status_code=result.status_code, load_time_ms=result.load_time_ms,
            html_characters=len(result.html), cleaned_html_characters=len(cleaned),
            screenshot_path=result.screenshot_path, cleaned_html_preview=cleaned[:3000])
        db.add(record)
        if site:
            site.status = "captured"
        db.commit()
        db.refresh(record)
        return serialize_capture(record)
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
    return [serialize_capture(item) for item in db.scalars(stmt).all()]

@router.get("/{capture_id}")
def get_capture(capture_id: int, db: Session = Depends(get_db)):
    item = db.get(CaptureRun, capture_id)
    if not item:
        raise HTTPException(404, "Capture record not found.")
    return serialize_capture(item)
