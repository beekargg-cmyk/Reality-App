import requests

API_BASE = "https://stream.wb.ru"
token = "1.100.82ee394fee3e4536991fdee769fb7019.MTV8OTQuMTMxLjExNy4yOXxNb3ppbGxhLzUuMCBBcHBsZVdlYnNpdGUvNTM3LjM2fC1lM1LCBsaWtlbHl2tkSBDaHJvbWUtMTQ4IjAuMC4wInFhZmFyaS81MzcuMzZ8MTc3OTg1NjMyOHxyZXVzYWJsZXVwYGV5SnM5ZWE5vSWpvaUl1dMD1MHwxOHwxNzc5Njc5MDM1fDE%3D.MEUCIQCIs3HSWWRv%2FiibcYjK0rdJN37b0WyehUSgKKP4LwAurgIgGjSwLnwPQKmCHj29Ug3AXEUSwxsIXako9nxPjNZLhI%3D"

headers = {
    "User-Agent": "Mozilla/5.0 (Linux x86_64)",
    "Content-Type": "application/json"
}
cookies = {"x_wbaas_token": token}

endpoints = [
    "/auth/api/v1/auth/user/me",
    "/auth/api/v1/auth/user/profile",
    "/auth/api/v1/auth/user/info",
    "/auth/api/v1/auth/user/session",
    "/auth/api/v1/auth/user/refresh",
    "/auth/api/v1/auth/user/login",
    "/auth/api/v1/auth/user/current"
]

for ep in endpoints:
    url = f"{API_BASE}{ep}"
    try:
        # Try GET
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=5)
        print(f"GET {ep} -> Status: {resp.status_code}")
        if resp.status_code == 200:
            print("Response:", resp.text[:200])
        # Try POST
        resp = requests.post(url, json={}, headers=headers, cookies=cookies, timeout=5)
        print(f"POST {ep} -> Status: {resp.status_code}")
        if resp.status_code == 200:
            print("Response:", resp.text[:200])
    except Exception as e:
        print(f"Error {ep}: {e}")
