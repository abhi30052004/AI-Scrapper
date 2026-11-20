import csv
import io
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.schemas import ExtractionRequest
from app.services.extraction_service import (
    run_extraction,
    get_extraction_run,
    initialize_extraction_db,
)
from app.services.onboarding import get_database_path

import sqlite3


router = APIRouter(
    prefix="/api/extraction",
    tags=["Extraction"],
)


@router.post("/run")
async def extract(payload: ExtractionRequest):
    try:
        return await run_extraction(
            config_id=payload.config_id,
            max_pages_override=payload.max_pages,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Extraction failed: {type(exc).__name__}: {exc}",
        ) from exc


@router.get("/runs")
def list_extraction_runs():
    initialize_extraction_db()

    with sqlite3.connect(get_database_path()) as conn:
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT id, config_id, start_url,
                   pages_crawled, record_count, created_at
            FROM extraction_runs
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


@router.get("/runs/{run_id}")
def read_extraction_run(run_id: int):
    try:
        return get_extraction_run(run_id)

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@router.get("/runs/{run_id}/export")
def export_extraction_run(
    run_id: int,
    format: str = Query(default="csv"),
):
    if format not in {"csv", "json"}:
        raise HTTPException(
            status_code=400,
            detail="Format must be csv or json",
        )

    try:
        result = get_extraction_run(run_id)

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    records = result["records"]

    if format == "json":
        return Response(
            content=json.dumps(records, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={
                "Content-Disposition":
                    f'attachment; filename="extraction_{run_id}.json"'
            },
        )

    output = io.StringIO()

    if records:
        fieldnames = list(
            dict.fromkeys(
                key
                for record in records
                for key in record.keys()
            )
        )

        writer = csv.DictWriter(
            output,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(records)

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition":
                f'attachment; filename="extraction_{run_id}.csv"'
        },
    )