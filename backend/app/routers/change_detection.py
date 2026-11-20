
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.change_detection_service import (
    run_change_detection,
    list_change_reports,
    get_change_report,
)

router = APIRouter(
    prefix="/api/changes",
    tags=["Change Detection"],
)


class ChangeDetectionRequest(BaseModel):
    old_run_id: int = Field(gt=0)
    new_run_id: int = Field(gt=0)


@router.post("/compare")
def compare_runs(payload: ChangeDetectionRequest):
    try:
        return run_change_detection(
            old_run_id=payload.old_run_id,
            new_run_id=payload.new_run_id,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Change detection failed: {type(exc).__name__}: {exc}",
        ) from exc


@router.get("/reports")
def get_reports():
    return list_change_reports()


@router.get("/reports/{report_id}")
def read_report(report_id: int):
    try:
        return get_change_report(report_id)

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
