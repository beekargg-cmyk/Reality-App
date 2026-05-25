import requests

API_BASE = "https://stream.wb.ru"
slug = "da_tkzkdcnf"

endpoints = [
    f"/api-room/api/v2/room/slug/{slug}",
    f"/api-room/api/v2/room/{slug}",
    f"/api-room/api/v1/room/slug/{slug}",
    f"/api-room/api/v1/room/{slug}",
    f"/api-room/api/v2/room/info/{slug}",
    f"/api-room/api/v2/room/by-slug/{slug}",
    f"/api-room/api/v1/room/by-slug/{slug}"
]

headers = {
    "User-Agent": "Mozilla/5.0 (Linux x86_64)",
    "Content-Type": "application/json"
}

for ep in endpoints:
    url = f"{API_BASE}{ep}"
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        print(f"GET {ep} -> Status: {resp.status_code}")
        if resp.status_code == 200:
            print("Response:", resp.text)
    except Exception as e:
        print(f"Error {ep}: {e}")
