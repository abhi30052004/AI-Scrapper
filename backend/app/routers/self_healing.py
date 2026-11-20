from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.self_healing_service import run_self_healing
from app.services.onboarding import (
    list_repair_history,
    get_repair_history,
    save_config,
    update_repair_review,
)

router = APIRouter(
    prefix="/api/self-healing",
    tags=["Self-Healing"],
)


class SelfHealingRequest(BaseModel):
    config_id: int = Field(gt=0)

class RepairReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")

@router.post("/run")
async def trigger_self_healing(request: SelfHealingRequest):
    try:
        return await run_self_healing(request.config_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Self-healing failed: {str(exc)[:300]}",
        ) from exc


@router.get("/history")
def repair_history_list():
    return {
        "total": len(list_repair_history()),
        "history": list_repair_history(),
    }

@router.get("/history/pending")
def pending_repair_history():
    pending = [
        repair
        for repair in list_repair_history()
        if repair["status"] == "human_review_required"
    ]

    return {
        "total": len(pending),
        "history": pending,
    }

@router.get("/history/{repair_id}")
def repair_history_detail(repair_id: int):
    result = get_repair_history(repair_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Repair history record not found",
        )

    return result

@router.post("/history/{repair_id}/review")
def review_repair(
    repair_id: int,
    request: RepairReviewRequest,
):
    repair = get_repair_history(repair_id)

    if repair is None:
        raise HTTPException(
            status_code=404,
            detail="Repair history record not found",
        )

    if repair["status"] != "human_review_required":
        raise HTTPException(
            status_code=400,
            detail="This repair is not waiting for human review",
        )

    if request.decision == "approve":
        save_result = {
            "config": repair["proposed_config"],
            "records": repair["sample_records"],
            "confidence": repair["confidence"],
            "status": "human_approved",
        }

        saved_version = save_config(
            repair["site_url"],
            save_result,
        )

        updated = update_repair_review(
            repair_id,
            "approved",
            saved_version["id"],
        )

        if not updated:
            raise HTTPException(
                status_code=409,
                detail="Could not update repair review status",
            )

        return {
            "message": "Repair approved and saved as a new configuration version",
            "repair_id": repair_id,
            "status": "approved",
            "saved_version": saved_version,
        }

    updated = update_repair_review(
        repair_id,
        "rejected_by_human",
    )

    if not updated:
        raise HTTPException(
            status_code=409,
            detail="Could not update repair review status",
        )

    return {
        "message": "Repair rejected successfully",
        "repair_id": repair_id,
        "status": "rejected_by_human",
    }