import os
import re

html_path = r"c:\Users\ACER\Desktop\Nirakshan-AI\static\index.html"
js_path = r"c:\Users\ACER\Desktop\Nirakshan-AI\static\js/app.js"

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

with open(js_path, "r", encoding="utf-8") as f:
    js_content = f.read()

# Find all document.getElementById("...") in js
get_elem_ids = re.findall(r'document\.getElementById\(["\']([^"\']+)["\']\)', js_content)
unique_ids = sorted(list(set(get_elem_ids)))

print(f"Total getElementById calls: {len(get_elem_ids)}")
print(f"Unique IDs in JS: {len(unique_ids)}")

missing_ids = []
for elem_id in unique_ids:
    pattern = f'id="{elem_id}"'
    pattern_single = f"id='{elem_id}'"
    if pattern not in html_content and pattern_single not in html_content:
        missing_ids.append(elem_id)

print(f"\nMissing element IDs in index.html ({len(missing_ids)}):")
for m in missing_ids:
    print(f"  - {m}")
