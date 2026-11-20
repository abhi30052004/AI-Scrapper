
import copy

from app.services.extraction_service import get_extraction_run
from app.services.change_detection_service import compare_extractions


old_run = get_extraction_run(1)
new_run = get_extraction_run(2)

# Keep original records unchanged
old_records = copy.deepcopy(old_run["records"])
new_records = copy.deepcopy(new_run["records"])

# Simulate one modified product
new_records[0]["price"] = "£99.99"

# Simulate one newly added product
new_records.append({
    "title": "Test New Book",
    "price": "£19.99",
    "rating": "star-rating five",
    "availability": "In stock",
    "product_url": "https://example.com/new-book"
})

# Simulate one removed product
new_records.pop(1)


# Test the comparison logic using temporary run data
from unittest.mock import patch

with patch(
    "app.services.change_detection_service.get_extraction_run"
) as mock_get_run:

    mock_get_run.side_effect = [
        {**old_run, "records": old_records},
        {**new_run, "records": new_records}
    ]

    report = compare_extractions(1, 2)

print("\nCHANGE DETECTION TEST RESULTS")
print("=" * 40)
print("Added:", report["summary"]["added"])
print("Removed:", report["summary"]["removed"])
print("Modified:", report["summary"]["modified"])
print("Unchanged:", report["summary"]["unchanged"])

assert report["summary"]["added"] == 1
assert report["summary"]["removed"] == 1
assert report["summary"]["modified"] == 1
assert report["summary"]["unchanged"] == 18

print("\nSUCCESS: All change detection tests passed!")
