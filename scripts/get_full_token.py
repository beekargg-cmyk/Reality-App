import json

har_path = "stream.wb.ru.har"

with open(har_path, "r", encoding="utf-8") as f:
    data = json.load(f)

entries = data.get("log", {}).get("entries", [])
entry = entries[17]
req = entry.get("request", {})

for h in req.get("headers", []):
    if h.get("name").lower() == "x-wbaas-token":
        print("TOKEN:", h.get("value"))
