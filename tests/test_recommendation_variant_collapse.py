"""Regression: obvious reuploads/interval variants occupy one suggestion row."""

from modagent.recommendation_ui import normalize_recommendations


payload = normalize_recommendations({
    "recommendations": [],
    "workshop": [
        {"id": "1", "name": "Dead Bodies Disappear Faster (20 seconds) (reupload)",
         "summary": "Remove bodies after 20 seconds.", "_detail_verified": True},
        {"id": "2", "name": "Dead Bodies Disappear Faster (5 seconds) (reupload)",
         "summary": "Remove bodies after 5 seconds.", "_detail_verified": True},
        {"id": "3", "name": "Different Gameplay Feature",
         "summary": "A different feature.", "_detail_verified": True},
    ],
}, limit=10)

items = payload["items"]
assert len(items) == 2, items
family = next(item for item in items if "Dead Bodies" in item["name"])
assert len(family.get("variant_alternatives") or []) == 1, family
print("RECOMMENDATION VARIANT COLLAPSE PASSED")
