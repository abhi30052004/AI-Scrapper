from app.services.extraction_service import get_saved_config
from app.services.onboarding import save_repair_history

saved = get_saved_config(5)

if not saved:
    raise ValueError("Config ID 5 not found")

repair_id = save_repair_history(
    original_config_id=5,
    site_url=saved["site_url"],
    status="human_review_required",
    confidence=0.75,
    ai_confidence=0.80,
    reason="Testing human approval workflow",
    failure_report={"test": True},
    proposed_config=saved["config"],
    sample_records=[{"title": "Human Review Test"}],
)

print("Pending review record created!")
print("Repair history ID:", repair_id)