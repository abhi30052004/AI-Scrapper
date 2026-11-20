
from app.services.extraction_service import get_saved_config
from app.services.onboarding import save_config

# Load the working configuration.
saved = get_saved_config(2)
config = saved["config"]

# Intentionally break the product container selector.
config["item_selector"] = "article.product_pod_broken"

# Save as a separate test configuration.
result = {
    "config": config,
    "records": [],
    "confidence": 0.0,
    "status": "test_broken",
}

created = save_config(saved["site_url"], result)

print("Broken test configuration created:")
print(created)
print("Original config ID:", 2)
print("Broken config ID:", created["id"])
print("Broken selector:", config["item_selector"])
