import asyncio
import json
import requests
import sys
import subprocess
from sqlalchemy import select
from app.database import async_session
from app.models import Server

API_BASE = "https://stream.wb.ru"

def create_wb_room() -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux x86_64)", 
        "Content-Type": "application/json"
    }
    proxies = {
        "http": "socks5://127.0.0.1:20001",
        "https": "socks5://127.0.0.1:20001"
    }
    print("[AUTO_ROTATE] Registering guest on WB Stream...")
    reg_req = requests.post(
        f"{API_BASE}/auth/api/v1/auth/user/guest-register", 
        json={
            "displayName": "ServerBot", 
            "device": {
                "deviceName": "Linux", 
                "deviceType": "PARTICIPANT_DEVICE_TYPE_WEB_DESKTOP"
            }
        }, 
        headers=headers,
        proxies=proxies,
        timeout=15
    )
    reg_req.raise_for_status()
    auth_data = reg_req.json()
    accessToken = auth_data['accessToken']
    
    headers["Authorization"] = f"Bearer {accessToken}"
    print("[AUTO_ROTATE] Creating WB Stream room...")
    room_req = requests.post(
        f"{API_BASE}/api-room/api/v2/room", 
        json={
            "roomType": "ROOM_TYPE_ALL_ON_SCREEN", 
            "roomPrivacy": "ROOM_PRIVACY_FREE"
        }, 
        headers=headers,
        proxies=proxies,
        timeout=15
    )
    print("[AUTO_ROTATE] Response status:", room_req.status_code)
    print("[AUTO_ROTATE] Response text:", room_req.text)
    room_req.raise_for_status()
    room_data = room_req.json()
    room_id = room_data["roomId"]
    print(f"[AUTO_ROTATE] New WB Room created: {room_id}")
    return room_id

async def update_db_and_get_node(room_id: str) -> tuple[str, str, str]:
    async with async_session() as s:
        res = await s.execute(select(Server).where(Server.id == 311))
        srv = res.scalar_one_or_none()
        if not srv:
            raise Exception("Server 311 not found in DB")
        
        config = dict(srv.config or {})
        config['olcrtc_room'] = room_id
        config['olcrtc_transport'] = 'vp8channel'
        srv.config = config
        
        s.add(srv)
        await s.commit()
        print("[AUTO_ROTATE] Updated database for Server 311")
        
        node_ip = srv.ip
        key = config.get('olcrtc_key', '49cd67cddbaef3bc3e3196fad1f0669cedae5632412bfb8cbfa43dc4ece9baaf')
        title = srv.name or "Test_OLC-RTC"
        return node_ip, key, title

def upload_to_yandex_disk(room_id: str, key: str, title: str):
    # Upload room links to Yandex Disk
    wb_link = f"olcrtc://{room_id}:{key}?name={title}+(Wildberries+Stream)&carrier=wbstream&transport=vp8channel"
    yandex_link = f"olcrtc://01002354213379:{key}?name={title}+(Yandex+Telemost)&carrier=telemost&transport=vp8channel"
    jazz_link = f"olcrtc://678bno:uchfuva2:{key}?name={title}+(SberJazz)&carrier=jazz&transport=vp8channel"
    content = f"{wb_link}\n{yandex_link}\n{jazz_link}"
    url = "https://webdav.yandex.ru/room.txt"
    print("[AUTO_ROTATE] Uploading links to Yandex Disk...")
    resp = requests.put(url, data=content, auth=('k4rkar567', 'cnmmpfkwgdcmnijs'))
    resp.raise_for_status()
    print("[AUTO_ROTATE] Uploaded to Yandex Disk successfully")

def update_node_server(node_ip: str, room_id: str, key: str):
    print(f"[AUTO_ROTATE] Updating Node Server ({node_ip}) via SSH...")
    env_content = f"OLCRTC_ROOM={room_id}\\nOLCRTC_KEY={key}"
    
    # We use sshpass to SSH into Server 311 and update env config, then restart olcrtc-wb
    cmd = f"echo -e '{env_content}' > /etc/olcrtc-wb.env && systemctl restart olcrtc-wb"
    
    # Run via sshpass which is installed on the panel server
    ssh_cmd = f"sshpass -p 'Petya2809' ssh -o StrictHostKeyChecking=no root@{node_ip} \"{cmd}\""
    res = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        raise Exception(f"Failed to update node server via SSH: {res.stderr}")
    print("[AUTO_ROTATE] Node server updated and restarted successfully")

async def main():
    try:
        room_id = create_wb_room()
        node_ip, key, title = await update_db_and_get_node(room_id)
        upload_to_yandex_disk(room_id, key, title)
        update_node_server(node_ip, room_id, key)
        print("[AUTO_ROTATE] ROTATE ROOM SUCCESSFUL!")
    except Exception as e:
        print(f"[AUTO_ROTATE] ERROR: {e}")

if __name__ == '__main__':
    asyncio.run(main())
