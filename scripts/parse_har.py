import json

har_path = "stream.wb.ru.har"

print("Loading HAR file...")
with open(har_path, "r", encoding="utf-8") as f:
    data = json.load(f)

entries = data.get("log", {}).get("entries", [])
print(f"Total entries: {len(entries)}")

print("\n--- Searching for endpoints of interest on stream.wb.ru ---")
for i, entry in enumerate(entries):
    req = entry.get("request", {})
    resp = entry.get("response", {})
    url = req.get("url", "")
    method = req.get("method", "")
    status = resp.get("status", 0)
    
    if "stream.wb.ru" not in url:
        continue
        
    # Check if the response contains tokens
    resp_text = ""
    content = resp.get("content", {})
    if "text" in content:
        resp_text = content.get("text", "")
        
    # Filter for room or auth related calls
    if "api-room" in url or "auth/api" in url or "da_tkzkdcnf" in url or "token" in url.lower():
        has_token = "token" in resp_text.lower() or "accesstoken" in resp_text.lower()
        print(f"[{i}] {method} {url} -> Status {status} (Has token in response: {has_token})")
        post_data = req.get("postData", {})
        if post_data:
            print(f"    Post Data: {post_data.get('text', '')}")
        if resp_text:
            print(f"    Response Preview: {resp_text[:300]}")
        print("-" * 50)
