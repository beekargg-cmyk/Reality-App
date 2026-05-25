import asyncio
import sys
import requests
import subprocess
from sqlalchemy import select
from app.database import async_session
from app.models import Server

# We expect the room ID as the first argument
if len(sys.argv) < 2:
    print("Usage: python3 update_room.py <new_room_id>")
    sys.exit(1)

new_room_id = sys.argv[1].strip()
if not new_room_id:
    print("Error: room ID cannot be empty")
    sys.exit(1)

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
        print(f"[UPDATE_ROOM] Updated database for Server 311 (room: {room_id})")
        
        node_ip = srv.ip
        key = config.get('olcrtc_key', '49cd67cddbaef3bc3e3196fad1f0669cedae5632412bfb8cbfa43dc4ece9baaf')
        title = srv.name or "Test_OLC-RTC"
        return node_ip, key, title

def upload_to_yandex_disk(room_id: str, key: str, title: str):
    wb_link = f"olcrtc://{room_id}:{key}?name={title}+(Wildberries+Stream)&carrier=wbstream&transport=vp8channel"
    yandex_link = f"olcrtc://01002354213379:{key}?name={title}+(Yandex+Telemost)&carrier=telemost&transport=vp8channel"
    jazz_link = f"olcrtc://678bno:uchfuva2:{key}?name={title}+(SberJazz)&carrier=jazz&transport=vp8channel"
    content = f"{wb_link}\n{yandex_link}\n{jazz_link}"
    url = "https://webdav.yandex.ru/room.txt"
    print("[UPDATE_ROOM] Uploading links to Yandex Disk...")
    resp = requests.put(url, data=content, auth=('k4rkar567', 'cnmmpfkwgdcmnijs'))
    resp.raise_for_status()
    print("[UPDATE_ROOM] Uploaded to Yandex Disk successfully")

def update_node_server(node_ip: str, room_id: str, key: str):
    print(f"[UPDATE_ROOM] Updating Node Server ({node_ip}) via SSH...")
    env_content = f"OLCRTC_ROOM={room_id}\\nOLCRTC_KEY={key}"
    cmd = f"echo -e '{env_content}' > /etc/olcrtc-wb.env && systemctl restart olcrtc-wb"
    ssh_cmd = f"sshpass -p 'Petya2809' ssh -o StrictHostKeyChecking=no root@{node_ip} \"{cmd}\""
    res = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        raise Exception(f"Failed to update node server via SSH: {res.stderr}")
    print("[UPDATE_ROOM] Node server updated and restarted successfully")

async def main():
    try:
        node_ip, key, title = await update_db_and_get_node(new_room_id)
        upload_to_yandex_disk(new_room_id, key, title)
        update_node_server(node_ip, new_room_id, key)
        print("[UPDATE_ROOM] ROOM UPDATE SUCCESSFUL!")
    except Exception as e:
        print(f"[UPDATE_ROOM] ERROR: {e}")

if __name__ == '__main__':
    asyncio.run(main())
