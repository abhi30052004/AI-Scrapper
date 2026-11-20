
import json
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.capture import capture_page
from app.services.onboarding import (
    get_database_path,
    initialize_onboarding_db,
    run_onboarding,
    save_config,
)

router = APIRouter(prefix="/api/onboarding", tags=["AI Onboarding"])


class FieldRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: str = "string"
    required: bool = True
    example: str | None = None


class OnboardingRequest(BaseModel):
    url: str
    fields: list[FieldRequest]


class SaveRequest(BaseModel):
    url: str
    result: dict


@router.post("/generate")
async def generate_onboarding(payload: OnboardingRequest):
    try:
        capture = await capture_page(
            payload.url, "data/snapshots"
        )

        fields = [
            field.model_dump()
            for field in payload.fields
        ]

        result = run_onboarding(
            payload.url,
            fields,
            capture.html,
        )

        return {
            "message": "AI configuration generated successfully",
            "url": payload.url,
            "page_title": capture.page_title,
            **result,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Onboarding failed: {type(exc).__name__}: {exc}",
        ) from exc


@router.post("/save")
def save_onboarding(payload: SaveRequest):
    try:
        saved = save_config(payload.url, payload.result)
        return {
            "message": "Configuration saved",
            **saved,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Save failed: {exc}",
        ) from exc


@router.get("/configs")
def list_configs():
    initialize_onboarding_db()

    with sqlite3.connect(get_database_path()) as conn:
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT id, site_url, version, confidence,
                   status, created_at
            FROM scraper_configs
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


@router.get("/configs/{config_id}")
def get_config(config_id: int):
    initialize_onboarding_db()

    with sqlite3.connect(get_database_path()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM scraper_configs WHERE id = ?",
            (config_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(404, "Configuration not found")

    result = dict(row)
    result["config_json"] = json.loads(result["config_json"])
    result["sample_records"] = json.loads(result["sample_records"])

    return result
