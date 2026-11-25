from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.services.database_explorer_service import (
    get_recent_products,
    search_products,
    export_products_csv,
)

router = APIRouter(prefix="/api/products", tags=["Products Management"])


@router.get("/recent")
def recent_products(limit: int = Query(default=20, ge=1, le=100)):
    try:
        return get_recent_products(limit=limit)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch recent products: {exc}",
        ) from exc


@router.get("")
def list_products(
    search: str | None = Query(default=None),
    site_id: int | None = Query(default=None),
    run_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="id"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
):
    try:
        return search_products(
            search=search,
            site_id=site_id,
            run_id=run_id,
            page=page,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to search products: {exc}",
        ) from exc


@router.get("/export")
def export_products(
    search: str | None = Query(default=None),
    site_id: int | None = Query(default=None),
    run_id: int | None = Query(default=None),
):
    try:
        csv_content, filename = export_products_csv(
            search=search,
            site_id=site_id,
            run_id=run_id,
        )

        return Response(
            content=csv_content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to export products CSV: {exc}",
        ) from exc
