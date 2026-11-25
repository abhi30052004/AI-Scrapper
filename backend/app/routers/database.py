from fastapi import APIRouter, HTTPException, Query
from app.services.database_explorer_service import (
    get_database_overview,
    get_database_tables_metadata,
    get_table_data,
    clear_table,
    clear_all_tables,
)

router = APIRouter(prefix="/api/database", tags=["Database Explorer"])


@router.get("/overview")
def database_overview():
    try:
        return get_database_overview()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch database overview: {exc}",
        ) from exc


@router.get("/tables")
def database_tables():
    try:
        return get_database_tables_metadata()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list database tables: {exc}",
        ) from exc


@router.get("/tables/{table_name}")
def read_table(
    table_name: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    sort_by: str | None = Query(default=None),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
):
    try:
        return get_table_data(
            table_name=table_name,
            page=page,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read table '{table_name}': {exc}",
        ) from exc


@router.delete("/tables/{table_name}")
def delete_table_rows(table_name: str):
    """Clear all rows from a specific table. The table schema is preserved."""
    try:
        return clear_table(table_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear table '{table_name}': {exc}",
        ) from exc


@router.delete("/all")
def delete_all_data():
    """Clear all rows from every data table. Schemas are preserved."""
    try:
        return clear_all_tables()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear all tables: {exc}",
        ) from exc
