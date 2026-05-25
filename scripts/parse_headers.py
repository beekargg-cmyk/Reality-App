import json

har_path = "stream.wb.ru.har"

with open(har_path, "r", encoding="utf-8") as f:
    data = json.load(f)

entries = data.get("log", {}).get("entries", [])

def print_entry_details(index):
    if index >= len(entries):
        return
    entry = entries[index]
    req = entry.get("request", {})
    resp = entry.get("response", {})
    url = req.get("url", "")
    method = req.get("method", "")
    print(f"[{index}] {method} {url}")
    print("  Request Headers:")
    for h in req.get("headers", []):
        name = h.get("name")
        val = h.get("value")
        # Display all headers
        display_val = val[:100] + "..." if len(val) > 100 else val
        print(f"    {name}: {display_val}")
    print("  Response Status:", resp.get("status"))
    print("  Response Content:")
    content = resp.get("content", {})
    if "text" in content:
        print("    ", content.get("text", "")[:300])
    print("-" * 60)

print_entry_details(17)
print_entry_details(26)
print_entry_details(32)
print_entry_details(54)
