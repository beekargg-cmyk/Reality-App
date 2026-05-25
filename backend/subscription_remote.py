from fastapi import APIRouter, Depends, HTTPException, Response, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from app.database import get_db
from app.models import User, Cluster, Server, ClusterType, ServerRole
import time
import base64
import urllib.parse
import os
import html as html_mod
import hashlib
from datetime import datetime, timezone, timedelta
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter(tags=["subscription"])
limiter = Limiter(key_func=get_remote_address)

def format_bytes(n):
    if n is None: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"

# === Балансировка нагрузки ===
HEALTH_TIMEOUT = timedelta(minutes=60)  # Сервер считается оффлайн после 60 мин без отклика
W_CPU = 0.3
W_RAM = 0.2
W_ONLINE = 0.5

def calculate_server_score(server: Server) -> float:
    """Рассчитывает score нагрузки сервера. Чем ниже — тем лучше."""
    cpu = server.cpu or 0
    ram = server.ram or 0
    online = server.online_users or 0
    limit = server.user_limit or 100
    online_ratio = min((online / limit) * 100, 100) if limit > 0 else 100
    return W_CPU * cpu + W_RAM * ram + W_ONLINE * online_ratio

def is_server_healthy(server: Server) -> bool:
    """Проверяет, что сервер отвечал в последние 60 минут."""
    if not server.last_seen:
        return True  # Если ещё не проверяли — считаем живым
    now = datetime.now(timezone.utc)
    last = server.last_seen.replace(tzinfo=timezone.utc) if server.last_seen.tzinfo is None else server.last_seen
    return (now - last) < HEALTH_TIMEOUT

def sort_servers_balanced(servers: list, user_uuid: str) -> list:
    """Сортирует серверы по нагрузке с session persistence через хэш UUID."""
    # 1. Фильтруем оффлайн серверы
    healthy = [s for s in servers if is_server_healthy(s)]
    if not healthy:
        healthy = list(servers)  # Если все оффлайн — отдаём все (лучше чем ничего)
    
    # 2. Считаем score
    scored = [(s, calculate_server_score(s)) for s in healthy]
    
    # 3. Session persistence: добавляем стабильный сдвиг на основе UUID
    # Это делает определённого пользователя «привязанным» к конкретному серверу при равном score
    uuid_hash = int(hashlib.md5(user_uuid.encode()).hexdigest()[:8], 16)
    
    # Сортируем: основной критерий — score, при одинаковом score — стабильный порядок по UUID
    scored.sort(key=lambda x: (round(x[1], -1), (x[0].id + uuid_hash) % 1000))
    
    return [s for s, _ in scored]


@router.get("/api/sub/{token}")
@limiter.limit("30/minute")
async def get_subscription(request: Request, token: str, response: Response, session: AsyncSession = Depends(get_db)):
    # 1. Ищем юзера
    result = await session.execute(select(User).where(User.uuid == token))
    user = result.scalars().first()
    if not user: raise HTTPException(status_code=404, detail="User not found")
            
    invalid_state_msg = None
    now = datetime.now(timezone.utc)
    user_expires_at = user.expires_at.replace(tzinfo=timezone.utc) if user.expires_at and user.expires_at.tzinfo is None else user.expires_at

    if user_expires_at and user_expires_at <= now:
        invalid_state_msg = "❌ Ваша подписка истекла, продлите ее в боте"
    elif not user.is_active:
        invalid_state_msg = "❌ Вы отписались от спонсоров, перейдите в бота и подпишитесь заново"
    
    # 1b. Проверяем лимит трафика (флаг, не блокируем всю подписку)
    traffic_exceeded = False
    if not invalid_state_msg and user.traffic_limit and user.traffic_limit > 0:
        traffic_used = (user.last_traffic_up or 0) + (user.last_traffic_down or 0)
        if traffic_used >= user.traffic_limit:
            traffic_exceeded = True
            
    # 1c. Проверяем HWID (привязка к N устройствам)
    client_hwid = request.headers.get("x-hwid")
    client_ua = request.headers.get("user-agent", "")
    import logging as _log
    _logger = _log.getLogger("subscription")
    _logger.info(f"[HWID DEBUG] uuid={token} x-hwid={client_hwid!r} UA={client_ua[:60]}")
    if client_hwid and not invalid_state_msg:
        hwid_list = user.hwid or []
        if not isinstance(hwid_list, list):
            hwid_list = []
        device_limit = user.device_limit or 1
        _logger.info(f"[HWID DEBUG] uuid={token} current_hwid_list={hwid_list} device_limit={device_limit}")
        
        # Обновляем hwid_agents маппинг (hwid -> user-agent)
        agents = user.hwid_agents or {}
        if not isinstance(agents, dict):
            agents = {}
        
        if client_hwid in hwid_list:
            _logger.info(f"[HWID DEBUG] uuid={token} hwid already in list, skip")
            # Обновляем UA если изменился
            if client_ua and agents.get(client_hwid) != client_ua:
                agents[client_hwid] = client_ua
                user.hwid_agents = agents
                flag_modified(user, "hwid_agents")
        elif len(hwid_list) < device_limit:
            # Есть свободный слот — привязываем
            hwid_list.append(client_hwid)
            user.hwid = hwid_list
            flag_modified(user, "hwid")
            # Сохраняем user-agent
            if client_ua:
                agents[client_hwid] = client_ua
                user.hwid_agents = agents
                flag_modified(user, "hwid_agents")
            _logger.info(f"[HWID DEBUG] uuid={token} NEW hwid added! list now={hwid_list}, UA={client_ua[:40]}")
        else:
            # Лимит устройств превышен
            _logger.warning(f"[HWID DEBUG] uuid={token} LIMIT EXCEEDED hwid_list={hwid_list} limit={device_limit}")
            invalid_state_msg = f"❌ Достигнут лимит устройств ({device_limit}), отключите лишние в боте"
    elif not client_hwid:
        _logger.info(f"[HWID DEBUG] uuid={token} NO x-hwid header received!")
    
    # 1d. Логируем активность
    user.last_active_at = datetime.now(timezone.utc)
    await session.commit()

    # 2. Ищем кластер
    cluster_res = await session.execute(select(Cluster).where(Cluster.id == user.cluster_id))
    cluster = cluster_res.scalars().first()
    if not cluster: return "" 

    links = []
    links_data = [] # Для дашборда

    if invalid_state_msg:
        # User is invalid (expired, unsubscribed, or device limit) -> Show a placeholder server
        alias_enc = urllib.parse.quote(invalid_state_msg)
        params_dict = {
            "type": "tcp",
            "security": "reality",
            "pbk": "0000000000000000000000000000000000000000000",
            "fp": "chrome",
            "sni": "error.local",
            "sid": "00000000",
            "flow": "xtls-rprx-vision",
            "fragment": "100-200,10-20,tlshello",
            "xpadding": "true",
            "tcpNoDelay": "true"
        }
        q_str = urllib.parse.urlencode(params_dict)
        link_url = f"vless://{user.uuid}@127.0.0.1:443?{q_str}#{alias_enc}"
        links.append(link_url)
        links_data.append({"name": invalid_state_msg, "url": link_url})
    else:
        # 3. Фильтруем серверы
        query = select(Server).where(Server.cluster_id == cluster.id)
        # Исключаем exit-сервера, чтобы не выдавать их клиентам, даже если каскад добавлен в обычный кластер
        query = query.where(Server.role.in_([ServerRole.standalone, ServerRole.entry]))
        servers_res = await session.execute(query)
        servers_raw = servers_res.scalars().all()
        
        # 4. Балансировка по локациям
        # Группируем по (location, role, metered) — чтобы standalone, entry и entry-тариф
        # были РАЗНЫМИ группами даже при одинаковой стране.
        # Внутри каждой группы выбираем наименее нагруженный сервер.
        
        from collections import defaultdict
        location_groups = defaultdict(list)
        no_location_servers = []
        
        for s in servers_raw:
            if s.location:
                # Ключ: (страна, роль, тариф) → разные группы
                group_key = (s.location, s.role.value if hasattr(s.role, 'value') else str(s.role), bool(s.metered))
                location_groups[group_key].append(s)
            else:
                no_location_servers.append(s)
        
        # Для каждой группы: выбираем наименее нагруженный healthy сервер
        balanced_servers = []
        for group_key, group in sorted(location_groups.items()):
            healthy = [s for s in group if is_server_healthy(s)]
            if not healthy:
                # Фильтруем серверы, которые мертвы более 24 часов — не показываем их вообще
                now = datetime.now(timezone.utc)
                recently_seen = [s for s in group if s.last_seen and 
                    (now - (s.last_seen.replace(tzinfo=timezone.utc) if s.last_seen.tzinfo is None else s.last_seen)).total_seconds() < 86400]
                if recently_seen:
                    healthy = recently_seen
                else:
                    continue  # Все мертвы более 24ч — пропускаем группу
            # Сортируем по score, при равном — стабильный порядок по UUID юзера
            uuid_hash = int(hashlib.md5(token.encode()).hexdigest()[:8], 16)
            healthy.sort(key=lambda s: (calculate_server_score(s), (s.id + uuid_hash) % 1000))
            balanced_servers.append(healthy[0])  # Лучший сервер для этой группы
        
        # Добавляем серверы без location (как раньше, все)
        balanced_servers.extend(sort_servers_balanced(no_location_servers, token))
    
        # 5. Генерируем ссылки
        metered_stub_added = False
        for server in balanced_servers:
            inbounds = server.inbounds if server.inbounds else []
            # Пропускаем серверы без inbounds (не установлены)
            if not inbounds:
                continue
                
            # --- OlcRTC Link Generation ---
            olcrtc_room = (server.config or {}).get("olcrtc_room")
            olcrtc_key = (server.config or {}).get("olcrtc_key")
            
            if olcrtc_room and olcrtc_key:
                # Generate three parallel carriers: Wildberries Stream, Yandex Telemost, SberJazz
                carriers = [
                    ("wbstream", "Wildberries Stream", "vp8channel", "019e5db3-2741-7f3f-a216-b264004617d8", True),
                    ("telemost", "Yandex Telemost", "vp8channel", "01002354213379", False),
                    ("jazz", "SberJazz", "vp8channel", "678bno:uchfuva2", False)
                ]
                for carrier_val, carrier_name, transport_val, def_room, is_dynamic in carriers:
                    alias = f"{server.name} ({carrier_name})"
                    alias_clean = alias.replace("[", "").replace("]", "").strip()
                    
                    if is_dynamic:
                        room_id_val = olcrtc_room
                        if not room_id_val or room_id_val in ("18462804720485", "019e5d75-3d01-762b-b84f-44eb1fa52b72"):
                            room_id_val = def_room
                    else:
                        room_id_val = def_room

                    params_dict = {
                        "name": alias_clean,
                        "user_id": user.uuid,
                        "client_id": "v2raytun",
                        "carrier": carrier_val,
                        "transport": transport_val
                    }
                    q_str = urllib.parse.urlencode(params_dict)
                    link_url = f"olcrtc://{room_id_val}:{olcrtc_key}?{q_str}"
                    links.append(link_url)
                    links_data.append({"name": alias, "url": link_url})
                continue
            # ------------------------------
            
            # Metered-серверы при исчерпании трафика — заглушка вместо удаления
            if traffic_exceeded and server.metered:
                if not metered_stub_added:
                    stub_msg = "⛔ ГБ закончились — проверьте ТГ бота"
                    stub_alias = urllib.parse.quote(stub_msg)
                    stub_params = {
                        "type": "tcp",
                        "security": "reality",
                        "pbk": "0000000000000000000000000000000000000000000",
                        "fp": "chrome",
                        "sni": "error.local",
                        "sid": "00000000",
                        "flow": "xtls-rprx-vision",
                        "fragment": "100-200,10-20,tlshello",
                        "xpadding": "true",
                        "tcpNoDelay": "true"
                    }
                    stub_q = urllib.parse.urlencode(stub_params) + "&spx=/"
                    stub_link = f"vless://{user.uuid}@127.0.0.1:443?{stub_q}#{stub_alias}"
                    links.append(stub_link)
                    links_data.append({"name": stub_msg, "url": stub_link})
                    metered_stub_added = True
                continue
            # Если это каскадный сервер с exit_name в inbounds — показываем каждый как отдельный exit
            has_exit_names = any(ib.get("exit_name") for ib in inbounds)
            if not has_exit_names:
                # Старое поведение: если обычный каскад без exit_name, берём только первый inbound
                inbounds = [inbounds[0]]
            for inbound in inbounds:
                port = inbound.get("port")
                sni = inbound.get("sni", "")
                if not port: continue
    
                protocol = inbound.get("protocol", "vless")
                
                # Используем exit_name если есть (multi-exit cascade)
                exit_name = inbound.get("exit_name", "")
                exit_location = inbound.get("exit_location", "")
                
                if exit_name:
                    alias = exit_name
                    # Добавляем флаг страны если есть location И имя ещё не содержит флаг
                    has_flag_emoji = any(0x1F1E6 <= ord(ch) <= 0x1F1FF for ch in alias[:4]) if alias else False
                    if exit_location and len(exit_location) == 2 and not has_flag_emoji:
                        cc = exit_location.upper()
                        c1 = ord(cc[0]) - 65 + 0x1F1E6
                        c2 = ord(cc[1]) - 65 + 0x1F1E6
                        flag = chr(c1) + chr(c2)
                        alias = f"{flag} {alias}"
                else:
                    alias = f"{server.name}"
                    if len(inbounds) > 1:
                        alias += f" [{port}]"
                
                alias_clean = alias.replace("[", "").replace("]", "").strip()
                alias_enc = urllib.parse.quote(alias_clean)
                
                if protocol in ["hy2", "hysteria2"]:
                    obfs = inbound.get("obfs", "")
                    pin = inbound.get("pinSHA256", "")
                    current_sni = sni if sni else "bing.com"
                    
                    params_dict = {
                        "sni": current_sni,
                        "insecure": "1"
                    }
                    if obfs:
                        params_dict["obfs"] = "salamander"
                        params_dict["obfs-password"] = obfs
                        
                    q_str = urllib.parse.urlencode(params_dict)
                    link_url = f"hysteria2://{user.uuid}@{server.ip.strip()}:{port}?{q_str}#{alias_enc}"
                elif protocol in ("vless-ws", "vless-grpc"):
                    # CloudShield: VLESS + XHTTP (splithttp) + TLS через CloudFlare CDN
                    xhttp_path = inbound.get("ws_path") or (server.config or {}).get("ws_path", "/xh")
                    # Для XHTTP используем путь без /ws- префикса
                    xhttp_path = xhttp_path.replace("/ws-", "/xh-")
                    current_sni = sni if sni else "cloudflare.com"
                    
                    params_dict = {
                        "type": "xhttp",
                        "security": "tls",
                        "sni": current_sni,
                        "host": current_sni,
                        "path": xhttp_path,
                        "fp": "chrome",
                        "mode": "auto",
                        "allowInsecure": "1"
                    }
                    
                    q_str = urllib.parse.urlencode(params_dict)
                    link_url = f"vless://{user.uuid}@{current_sni}:{port}?{q_str}#{alias_enc}"
                    
                elif inbound.get("transport") in ("ws", "xhttp") or (inbound.get("security") == "tls" and inbound.get("transport") not in (None, "tcp")):
                    # CDN Fronting: VLESS + XHTTP/WS + TLS
                    cdn_domain = inbound.get("sni") or (server.config or {}).get("cdn_domain", "")
                    xhttp_path = inbound.get("ws_path") or (server.config or {}).get("ws_path", "/")
                    current_sni = cdn_domain if cdn_domain else sni
                    transport = inbound.get("transport", "xhttp")
                    
                    params_dict = {
                        "type": transport,
                        "security": "tls",
                        "sni": current_sni,
                        "host": current_sni,
                        "path": xhttp_path,
                        "fp": "chrome",
                        "allowInsecure": "1",
                        "alpn": "http/1.1"
                    }
                    if transport == "xhttp":
                        params_dict["mode"] = "auto"
                        params_dict.pop("alpn", None) # xhttp can use h2
                    
                    q_str = urllib.parse.urlencode(params_dict)
                    connect_addr = current_sni if current_sni else server.ip.strip()
                    link_url = f"vless://{user.uuid}@{connect_addr}:{port}?{q_str}#{alias_enc}"
                    
                else:
                    pbk = server.public_key or ""
                    sid = inbound.get("sid") or server.short_id or ""
                    current_sni = sni if sni else "images.samsung.com"
                    
                    # ★ Per-user SNI override (from diagnostics rotation)
                    user_sni_prefs = user.sni_preferences or {}
                    server_pref = user_sni_prefs.get(str(server.id))
                    if server_pref and isinstance(server_pref, dict) and server_pref.get("sni"):
                        current_sni = server_pref["sni"]
                    
                    params_dict = {
                        "type": "tcp",
                        "security": "reality",
                        "pbk": pbk,
                        "fp": "chrome",
                        "sni": current_sni,
                        "sid": sid,
                        "flow": "xtls-rprx-vision",
                        "tcpNoDelay": "true"
                    }
                    # Fragment/xpadding ломает Reality на каскадных Entry нодах
                    # (v2RayTun дробит ClientHello + шлёт noise → handshake fail)
                    # Добавляем только для НЕ-каскадных серверов
                    is_cascade = bool(server.role == "entry" or has_exit_names)
                    if not is_cascade:
                        params_dict["fragment"] = "100-200,10-20,tlshello"
                        params_dict["xpadding"] = "true"
                    
                    q_str = urllib.parse.urlencode(params_dict)
                    link_url = f"vless://{user.uuid}@{server.ip.strip()}:{port}?{q_str}#{alias_enc}"
                
                links.append(link_url)
                links_data.append({"name": alias, "url": link_url})
                
                # ★ Multi-SNI fallback: добавляем до 2 альтернативных ссылок с другими SNI
                # Это помогает пользователям, у которых провайдер блокирует основной SNI
                MAX_ALT_SNIS = 2
                if protocol not in ["hy2", "hysteria2", "vless-ws", "vless-grpc"] and \
                   not inbound.get("transport") in ("ws", "xhttp") and \
                   hasattr(server, 'available_snis') and server.available_snis:
                    alt_snis = [s for s in server.available_snis 
                                if s != current_sni and s != sni and len(s) > 3][:MAX_ALT_SNIS]
                    for alt_idx, alt_sni in enumerate(alt_snis, start=2):
                        alt_params = params_dict.copy()
                        alt_params["sni"] = alt_sni
                        alt_q = urllib.parse.urlencode(alt_params)
                        alt_alias = f"{alias_clean} [{alt_idx}]"
                        alt_alias_enc = urllib.parse.quote(alt_alias)
                        alt_link = f"vless://{user.uuid}@{server.ip.strip()}:{port}?{alt_q}#{alt_alias_enc}"
                        links.append(alt_link)
                        links_data.append({"name": alt_alias, "url": alt_link})

    # 5. Определение типа ответа (Браузер или Клиент)
    ua = request.headers.get("User-Agent", "").lower()
    is_browser = any(x in ua for x in ["mozilla", "chrome", "safari", "opera", "edge"])
    
    # Исключаем некоторые VPN клиенты
    if "clash" in ua or "v2ray" in ua or "nekobox" in ua or "shadowrocket" in ua or "happ" in ua:
        is_browser = False

    if is_browser:
        sub_url = str(request.url)
        exp_str = user.expires_at.strftime("%d.%m.%Y") if user.expires_at else "Бессрочно"
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&color=22d3ee&bgcolor=0a0a0a&data={urllib.parse.quote(sub_url)}"
        
        # === XSS PROTECTION: экранируем все пользовательские данные ===
        safe_email = html_mod.escape(user.email or "")
        safe_cluster = html_mod.escape(cluster.name or "")
        safe_sub_url = html_mod.escape(sub_url)
        # Для JS строки: экранируем обратные слэши, кавычки и HTML
        safe_sub_url_js = sub_url.replace("\\", "\\\\").replace("'", "\\'").replace("<", "\\x3c").replace(">", "\\x3e")

        configs_html = ""
        for item in links_data:
            safe_name = html_mod.escape(item['name'])
            safe_url = html_mod.escape(item['url'])
            safe_url_js = item['url'].replace("\\", "\\\\").replace("'", "\\'").replace('"', '&quot;').replace("<", "&lt;").replace(">", "&gt;")
            short = html_mod.escape(item['url'][:80] + ('...' if len(item['url']) > 80 else ''))
            configs_html += f"""
            <div class="cfg">
                <div class="cfg-info">
                    <div class="cfg-name">{safe_name}</div>
                    <div class="cfg-url">{short}</div>
                </div>
                <button class="mini-btn" onclick="cp('{safe_url_js}', this)">Копировать</button>
            </div>"""

        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reality VPN — Подписка</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background: #080808;
  color: #f1f5f9;
  font-family: 'Inter', system-ui, sans-serif;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 16px 80px;
  background-image: radial-gradient(ellipse at 50% 0%, rgba(34,211,238,0.07) 0%, transparent 65%);
}}
.logo {{ font-size: 12px; font-weight: 700; color: #22d3ee; letter-spacing: 0.18em; text-transform: uppercase; margin-bottom: 36px; }}
.card {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 24px; padding: 28px; width: 100%; max-width: 540px; margin-bottom: 12px; }}
.row {{ display: flex; align-items: center; gap: 14px; margin-bottom: 24px; }}
.av {{ width: 50px; height: 50px; border-radius: 14px; background: linear-gradient(135deg,#22d3ee22,#6366f122); border: 1px solid rgba(34,211,238,0.18); display: flex; align-items: center; justify-content: center; font-size: 20px; flex-shrink: 0; }}
.un {{ font-size: 16px; font-weight: 700; }}
.um {{ font-size: 12px; color: #6b7280; margin-top: 2px; }}
.stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 22px; }}
.sbox {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; padding: 12px 14px; }}
.sl {{ font-size: 10px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.09em; margin-bottom: 3px; }}
.sv {{ font-size: 18px; font-weight: 800; color: #22d3ee; }}
.sec {{ font-size: 10px; font-weight: 600; color: #6b7280; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 10px; }}
.subbox {{ background: rgba(34,211,238,0.04); border: 1px solid rgba(34,211,238,0.12); border-radius: 14px; padding: 16px; }}
.suburl {{ font-family: monospace; font-size: 11px; color: #94a3b8; word-break: break-all; line-height: 1.6; margin-bottom: 14px; }}
.brow {{ display: flex; gap: 8px; }}
.btn {{ flex: 1; padding: 10px; border: none; border-radius: 10px; font-size: 13px; font-weight: 600; cursor: pointer; font-family: inherit; transition: all .15s; }}
.bp {{ background: #22d3ee; color: #000; }}
.bp:hover {{ background: #06b6d4; }}
.bs {{ background: rgba(255,255,255,0.06); color: #f1f5f9; border: 1px solid rgba(255,255,255,0.09); }}
.bs:hover {{ background: rgba(255,255,255,0.1); }}
.qrb {{ display: none; align-items: center; gap: 18px; margin-top: 16px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.06); }}
.qri {{ width: 80px; height: 80px; border-radius: 10px; }}
.qrh {{ font-size: 12px; color: #6b7280; line-height: 1.6; }}
.cfg {{ display: flex; align-items: center; gap: 10px; padding: 12px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; margin-bottom: 8px; }}
.cfg-info {{ flex: 1; min-width: 0; }}
.cfg-name {{ font-size: 13px; font-weight: 600; margin-bottom: 3px; }}
.cfg-url {{ font-size: 10px; color: #6b7280; font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.mini-btn {{ flex-shrink: 0; padding: 7px 12px; background: rgba(34,211,238,0.08); border: 1px solid rgba(34,211,238,0.18); color: #22d3ee; border-radius: 8px; font-size: 11px; font-weight: 600; cursor: pointer; font-family: inherit; white-space: nowrap; transition: all .15s; }}
.mini-btn:hover {{ background: rgba(34,211,238,0.18); }}
.empty {{ text-align: center; color: #4b5563; font-size: 13px; padding: 24px; }}
.apps {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-top: 14px; padding-top: 14px; border-top: 1px solid rgba(255,255,255,0.06); }}
.app-btn {{ display: flex; flex-direction: column; align-items: center; gap: 5px; padding: 12px 8px; background: rgba(34,211,238,0.06); border: 1px solid rgba(34,211,238,0.15); border-radius: 12px; cursor: pointer; text-decoration: none; color: #22d3ee; font-size: 12px; font-weight: 700; transition: all .15s; text-align: center; }}
.app-btn:hover {{ background: rgba(34,211,238,0.15); border-color: rgba(34,211,238,0.3); transform: translateY(-1px); }}
.app-btn .ic {{ font-size: 22px; }}
.stores {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-top: 8px; }}
.store-btn {{ display: flex; align-items: center; justify-content: center; gap: 6px; padding: 10px 8px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 12px; cursor: pointer; text-decoration: none; color: #94a3b8; font-size: 11px; font-weight: 600; transition: all .15s; text-align: center; }}
.store-btn:hover {{ background: rgba(255,255,255,0.07); color: #f1f5f9; }}
.store-btn .ic {{ font-size: 16px; }}
.sec2 {{ font-size: 10px; font-weight: 600; color: #4b5563; text-transform: uppercase; letter-spacing: 0.1em; margin-top: 14px; margin-bottom: 6px; }}
.tabs {{ display: flex; gap: 4px; margin-top: 8px; background: rgba(255,255,255,0.03); border-radius: 12px; padding: 4px; }}
.tab {{ flex: 1; padding: 10px 6px; border: none; border-radius: 10px; background: transparent; color: #6b7280; font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit; transition: all .2s; }}
.tab.active {{ background: rgba(34,211,238,0.12); color: #22d3ee; }}
.tab:hover:not(.active) {{ color: #94a3b8; }}
.tab-content {{ display: none; margin-top: 8px; }}
.tab-content.active {{ display: block; }}
.acc {{ margin-bottom: 6px; border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; overflow: hidden; }}
.acc-btn {{ width: 100%; padding: 14px 16px; border: none; background: rgba(255,255,255,0.03); color: #f1f5f9; font-size: 14px; font-weight: 700; cursor: pointer; font-family: inherit; text-align: left; display: flex; align-items: center; gap: 8px; transition: all .15s; }}
.acc-btn:hover {{ background: rgba(255,255,255,0.06); }}
.acc-btn::after {{ content: '▸'; margin-left: auto; transition: transform .2s; color: #6b7280; font-size: 14px; }}
.acc-btn.open::after {{ transform: rotate(90deg); color: #22d3ee; }}
.acc-body {{ display: none; padding: 0 16px 16px; }}
.acc-body.show {{ display: block; }}
.badge {{ background: #22d3ee; color: #000; font-size: 9px; font-weight: 700; padding: 2px 8px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.05em; }}
.dl-btn {{ display: block; padding: 10px; background: rgba(34,211,238,0.06); border: 1px solid rgba(34,211,238,0.15); border-radius: 10px; color: #22d3ee; text-decoration: none; font-size: 13px; font-weight: 600; text-align: center; margin-bottom: 12px; transition: all .15s; }}
.dl-btn:hover {{ background: rgba(34,211,238,0.15); }}
.steps {{ padding-left: 20px; font-size: 13px; color: #94a3b8; line-height: 2; }}
.steps li {{ margin-bottom: 2px; }}
.steps b {{ color: #f1f5f9; }}
.tip {{ font-size: 12px; color: #6b7280; background: rgba(34,211,238,0.05); border-left: 3px solid rgba(34,211,238,0.3); padding: 8px 12px; border-radius: 0 8px 8px 0; margin-top: 8px; line-height: 1.5; }}
</style>
</head>
<body>
<div class="logo">⚡ Reality VPN</div>

<div class="card">
  <div class="row">
    <div class="av">👤</div>
    <div>
      <div class="un">{safe_email}</div>
      <div class="um">Кластер: {safe_cluster}</div>
    </div>
  </div>
  <div class="stats">
    <div class="sbox"><div class="sl">Срок действия</div><div class="sv">{exp_str}</div></div>
    <div class="sbox"><div class="sl">Серверов</div><div class="sv">{len(links)}</div></div>
  </div>
  <div class="sec">Ссылка подписки</div>
  <div class="subbox">
    <div class="suburl" id="su">{safe_sub_url}</div>
    <div class="brow">
      <button class="btn bp" onclick="cp(SUB_URL, this)">📎 Копировать ссылку</button>
      <button class="btn bs" onclick="toggleQR(this)">📷 QR-код</button>
    </div>
    <div class="sec2">Добавить подписку в приложение</div>
    <div class="apps" style="grid-template-columns: 1fr 1fr 1fr">
      <a class="app-btn" href="happ://add/{sub_url}" onclick="cp(SUB_URL, null)">
        <span class="ic">🔵</span>Happ
      </a>
      <a class="app-btn" href="v2raytun://import/{sub_url}">
        <span class="ic">🟣</span>V2RayTun
      </a>
      <a class="app-btn" href="hiddify://import/{sub_url}">
        <span class="ic">🟠</span>Hiddify
      </a>
      <a class="app-btn" href="v2rayng://install-config?url={sub_url}">
        <span class="ic">🟢</span>V2RayNG
      </a>
      <a class="app-btn" href="streisand://import/{sub_url}">
        <span class="ic">🔴</span>Streisand
      </a>
      <a class="app-btn" href="sing-box://import-remote-profile?url={sub_url}">
        <span class="ic">⚫</span>SingBox
      </a>
      <a class="app-btn" href="clash://install-config?url={sub_url}">
        <span class="ic">🔶</span>FlClash
      </a>
    </div>

    <div class="sec2">Скачать и настроить</div>
    <div class="tabs">
      <button class="tab active" onclick="showTab('ios',this)">📱 iOS</button>
      <button class="tab" onclick="showTab('android',this)">🤖 Android</button>
      <button class="tab" onclick="showTab('windows',this)">💻 Windows</button>
      <button class="tab" onclick="showTab('macos',this)">🍎 macOS</button>
      <button class="tab" onclick="showTab('tv',this)">📺 TV</button>
    </div>

    <div id="tab-ios" class="tab-content active">
      <div class="acc">
        <button class="acc-btn open" onclick="toggleAcc(this)">🟠 Hiddify <span class="badge">рекомендуем</span></button>
        <div class="acc-body show">
          <a class="dl-btn" href="https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532" target="_blank">📥 Скачать из App Store</a>
          <ol class="steps">
            <li>Скачайте и откройте приложение <b>Hiddify</b></li>
            <li>Нажмите кнопку <b>«Открыть в Hiddify»</b> выше, или скопируйте ссылку подписки</li>
            <li>В приложении нажмите <b>+</b> → <b>«Добавить из буфера обмена»</b></li>
            <li>Нажмите кнопку <b>подключения</b> для запуска VPN</li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">🔵 Happ</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973" target="_blank">📥 Скачать из App Store</a>
          <ol class="steps">
            <li>Скачайте и откройте <b>Happ</b></li>
            <li>Нажмите кнопку <b>«Открыть в Happ»</b> выше</li>
            <li>Подписка добавится автоматически, нажмите <b>подключение</b></li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">🟣 V2RayTun</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://apps.apple.com/app/v2raytun/id6476140590" target="_blank">📥 Скачать из App Store</a>
          <ol class="steps">
            <li>Скачайте и откройте <b>V2RayTun</b></li>
            <li>Нажмите кнопку <b>«Открыть в V2RayTun»</b> выше</li>
            <li>Или скопируйте ссылку и вставьте через <b>+</b> → <b>«Import from clipboard»</b></li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">🔴 Streisand</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://apps.apple.com/app/streisand/id6450534064" target="_blank">📥 Скачать из App Store</a>
          <ol class="steps">
            <li>Скачайте и откройте <b>Streisand</b></li>
            <li>Нажмите <b>«Открыть в Streisand»</b> выше</li>
            <li>Или: Настройки → Подписки → <b>+</b> → вставьте ссылку</li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">⚫ Shadowrocket</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://apps.apple.com/app/shadowrocket/id932747118" target="_blank">📥 Скачать из App Store (платный)</a>
          <ol class="steps">
            <li>Откройте <b>Shadowrocket</b></li>
            <li>Скопируйте ссылку подписки</li>
            <li>Нажмите <b>+</b> → Тип: <b>Subscribe</b> → вставьте URL → <b>Готово</b></li>
          </ol>
        </div>
      </div>
    </div>

    <div id="tab-android" class="tab-content">
      <div class="acc">
        <button class="acc-btn open" onclick="toggleAcc(this)">🟠 Hiddify <span class="badge">рекомендуем</span></button>
        <div class="acc-body show">
          <a class="dl-btn" href="https://play.google.com/store/apps/details?id=app.hiddify.com" target="_blank">📥 Скачать из Google Play</a>
          <ol class="steps">
            <li>Скачайте и откройте <b>Hiddify</b></li>
            <li>Нажмите кнопку <b>«Открыть в Hiddify»</b> выше</li>
            <li>Или нажмите <b>+</b> → <b>«Добавить из буфера обмена»</b></li>
            <li>Нажмите кнопку подключения</li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">🔵 Happ</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://play.google.com/store/apps/details?id=com.happproxy" target="_blank">📥 Скачать из Google Play</a>
          <ol class="steps">
            <li>Скачайте и откройте <b>Happ</b></li>
            <li>Нажмите <b>«Открыть в Happ»</b> выше</li>
            <li>Подписка добавится автоматически</li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">🟣 V2RayTun</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://play.google.com/store/apps/details?id=com.v2raytun.android" target="_blank">📥 Скачать из Google Play</a>
          <ol class="steps">
            <li>Скачайте и откройте <b>V2RayTun</b></li>
            <li>Нажмите <b>«Открыть в V2RayTun»</b> выше</li>
            <li>Или: <b>+</b> → <b>Import from clipboard</b></li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">🟢 V2RayNG</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://play.google.com/store/apps/details?id=com.v2ray.ang" target="_blank">📥 Скачать из Google Play</a>
          <ol class="steps">
            <li>Скачайте и откройте <b>V2RayNG</b></li>
            <li>Нажмите <b>«Открыть в V2RayNG»</b> выше</li>
            <li>Или: <b>+</b> → <b>Импорт из буфера</b></li>
            <li>Нажмите ▶ для подключения</li>
          </ol>
        </div>
      </div>
    </div>

    <div id="tab-windows" class="tab-content">
      <div class="acc">
        <button class="acc-btn open" onclick="toggleAcc(this)">🟠 Hiddify <span class="badge">рекомендуем</span></button>
        <div class="acc-body show">
          <a class="dl-btn" href="https://github.com/hiddify/hiddify-app/releases/latest" target="_blank">📥 Скачать с GitHub</a>
          <ol class="steps">
            <li>Скачайте <b>Hiddify-Setup.exe</b> и установите</li>
            <li>Скопируйте ссылку подписки выше</li>
            <li>В приложении: <b>+</b> → <b>Добавить из буфера</b></li>
            <li>Включите режим <b>VPN</b> в настройках для полного покрытия</li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">🔵 Happ</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://www.happ.su/main/ru" target="_blank">📥 Скачать Happ для ПК</a>
          <ol class="steps">
            <li>Скачайте и установите <b>Happ</b></li>
            <li>Скопируйте ссылку подписки</li>
            <li>Подписка → <b>+</b> → вставьте ссылку</li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">🟣 NekoRay / NekoBox</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://github.com/MatsuriDayo/nekoray/releases/latest" target="_blank">📥 Скачать с GitHub</a>
          <ol class="steps">
            <li>Скачайте архив, распакуйте, запустите <b>nekobox.exe</b></li>
            <li>Preferences → <b>Groups</b> → <b>New Group</b></li>
            <li>Type: <b>Subscription</b>, вставьте ссылку, нажмите OK</li>
            <li>Правый клик по группе → <b>Update Subscription</b></li>
            <li>Выберите сервер → <b>Start</b></li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">🟢 InvisibleMan XRay</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://github.com/InvisibleManVPN/InvisibleMan-XRayClient/releases/latest" target="_blank">📥 Скачать с GitHub</a>
          <ol class="steps">
            <li>Скачайте и запустите <b>Invisible Man XRay.exe</b></li>
            <li>Скопируйте ссылку подписки</li>
            <li>Settings → Subscription → вставьте URL → <b>Update</b></li>
            <li>Выберите сервер и нажмите <b>Run</b></li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">🔶 FlClash</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://github.com/chen08209/FlClash/releases/latest" target="_blank">📥 Скачать с GitHub</a>
          <ol class="steps">
            <li>Скачайте <b>FlClash-Setup.exe</b> и установите</li>
            <li>Скопируйте ссылку подписки</li>
            <li>Profiles → <b>+</b> → URL → вставьте ссылку → <b>Download</b></li>
            <li>Выберите прокси и нажмите подключение</li>
          </ol>
        </div>
      </div>
    </div>

    <div id="tab-macos" class="tab-content">
      <div class="acc">
        <button class="acc-btn open" onclick="toggleAcc(this)">🟠 Hiddify <span class="badge">рекомендуем</span></button>
        <div class="acc-body show">
          <a class="dl-btn" href="https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532" target="_blank">📥 Скачать из App Store</a>
          <ol class="steps">
            <li>Скачайте <b>Hiddify</b> из App Store (или <a href="https://github.com/hiddify/hiddify-app/releases/latest" target="_blank">с GitHub</a>)</li>
            <li>Нажмите <b>«Открыть в Hiddify»</b> выше</li>
            <li>Или: <b>+</b> → <b>Добавить из буфера обмена</b></li>
            <li>Включите режим <b>VPN</b></li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">🔵 Happ</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://www.happ.su/main/ru" target="_blank">📥 Скачать Happ для macOS</a>
          <ol class="steps">
            <li>Скачайте и установите <b>Happ</b></li>
            <li>Нажмите <b>«Открыть в Happ»</b> или вставьте ссылку</li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">🔶 FlClash</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://github.com/chen08209/FlClash/releases/latest" target="_blank">📥 Скачать с GitHub (.dmg)</a>
          <ol class="steps">
            <li>Скачайте <b>.dmg</b> файл и установите</li>
            <li>Скопируйте ссылку подписки</li>
            <li>Profiles → <b>+</b> → URL → вставьте → <b>Download</b></li>
          </ol>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">🔴 Streisand</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://apps.apple.com/app/streisand/id6450534064" target="_blank">📥 Скачать из App Store</a>
          <ol class="steps">
            <li>Скачайте <b>Streisand</b></li>
            <li>Нажмите <b>«Открыть в Streisand»</b> выше</li>
          </ol>
        </div>
      </div>
    </div>

    <div id="tab-tv" class="tab-content">
      <div class="acc">
        <button class="acc-btn open" onclick="toggleAcc(this)">📺 Apple TV (sing-box VT)</button>
        <div class="acc-body show">
          <a class="dl-btn" href="https://apps.apple.com/app/sing-box-vt/id6596397600" target="_blank">📥 Скачать из App Store (tvOS 17+)</a>
          <ol class="steps">
            <li>На Apple TV откройте <b>App Store</b> и найдите <b>sing-box VT</b></li>
            <li>Откройте приложение → <b>Remote Profile</b></li>
            <li>Введите ссылку подписки (удобнее диктовать через iPhone)</li>
            <li>Нажмите <b>Download</b> → включите профиль</li>
          </ol>
          <div class="tip">💡 Совет: откройте эту страницу на iPhone, скопируйте ссылку и используйте функцию «Ввод текста с iPhone» на Apple TV</div>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">📺 Android TV — V2RayTun</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://play.google.com/store/apps/details?id=com.v2raytun.android" target="_blank">📥 Скачать из Google Play</a>
          <ol class="steps">
            <li>На Android TV откройте <b>Google Play</b> и найдите <b>V2RayTun</b></li>
            <li>Откройте браузер на ТВ, зайдите на эту страницу подписки</li>
            <li>Скопируйте ссылку подписки</li>
            <li>В V2RayTun: <b>+</b> → <b>Import from clipboard</b></li>
          </ol>
          <div class="tip">💡 V2RayTun оптимизирован для управления пультом ТВ</div>
        </div>
      </div>
      <div class="acc">
        <button class="acc-btn" onclick="toggleAcc(this)">📺 Android TV — Hiddify</button>
        <div class="acc-body">
          <a class="dl-btn" href="https://play.google.com/store/apps/details?id=app.hiddify.com" target="_blank">📥 Скачать из Google Play</a>
          <ol class="steps">
            <li>Скачайте <b>Hiddify</b> из Google Play на ТВ</li>
            <li>Подключите мышь (для удобной навигации)</li>
            <li>Скопируйте ссылку подписки через браузер ТВ</li>
            <li><b>+</b> → <b>Добавить из буфера</b> → подключение</li>
          </ol>
        </div>
      </div>
    </div>

    <div class="qrb" id="qrb">
      <img class="qri" src="{qr_url}" alt="QR">
      <div class="qrh">Отсканируйте QR в приложении <b>Happ</b>, <b>V2RayTun</b>, <b>Hiddify</b> или другом VLESS-клиенте.</div>
    </div>
  </div>
</div>



<script>
const SUB_URL = '{safe_sub_url_js}';
function cp(t, b) {{
  if (!t) return;
  navigator.clipboard.writeText(t).then(() => {{
    if (b) {{
      const o = b.textContent;
      b.textContent = '✓ Скопировано!';
      setTimeout(() => b.textContent = o, 2200);
    }}
  }}).catch(() => {{
    // Fallback для iOS
    const ta = document.createElement('textarea');
    ta.value = t;
    ta.style.cssText = 'position:fixed;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    if (b) {{
      const o = b.textContent;
      b.textContent = '✓ Скопировано!';
      setTimeout(() => b.textContent = o, 2200);
    }}
  }});
}}
function toggleQR(btn) {{
  const qr = document.getElementById('qrb');
  const show = qr.style.display !== 'flex';
  qr.style.display = show ? 'flex' : 'none';
  btn.textContent = show ? '❌ Скрыть' : '📷 QR-код';
}}
function showTab(id, btn) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  btn.classList.add('active');
}}
function toggleAcc(btn) {{
  const body = btn.nextElementSibling;
  const isOpen = body.classList.contains('show');
  body.classList.toggle('show');
  btn.classList.toggle('open');
}}
</script>
</body>
</html>"""
        return HTMLResponse(content=html)

    # Подготовка данных пользователя
    upload = user.last_traffic_up or 0
    download = user.last_traffic_down or 0
    total = 0  # Не показываем лимит в приложении, только в ТГ-боте
    expire = int(user.expires_at.timestamp()) if user.expires_at else 4070908800 # Бессрочно

    # === GeoIP Routing для Happ (bypass российских сервисов) ===
    import json as _json
    happ_routing = {
        "RouteOrder": "BlockProxyDirect",
        "DirectSites": [
            "vk.com", "vk.ru", "userapi.com", "vk-cdn.net", "vkcdnservice.com",
            "vk.me", "vk.cc", "vkpay.io", "vkuservideo.net", "vkuseraudio.net",
            "vkapps.com", "vkforms.ru", "vk-portal.net", "vkuser.net",
            "mail.ru", "ok.ru", "odnoklassniki.ru", "okcdn.ru", "mycdn.me",
            "yandex.ru", "yandex.net", "ya.ru", "dzen.ru",
            "wildberries.ru", "wbbasket.ru", "wb.ru", "wbpay.ru", "wb-basket.ru",
            "geobasket.ru", "paywb.com", "rwb.ru", "wibes.ru",
            "ozon.ru", "ozon.by", "ozon.com", "ozon.kz", "ozon.tm", "ozone.ru",
            "ozonru.me", "ozonusercontent.com", "o3.ru", "o3t.ru",
            "avito.ru", "avito.st",
            "sberbank.ru", "online.sberbank.ru",
            "tinkoff.ru", "cdn-tinkoff.ru",
            "alfabank.ru", "alfadirect.ru", "myapelsin.ru",
            "vtb.ru", "online.vtb.ru",
            "gosuslugi.ru", "esia.gosuslugi.ru",
            "2gis.ru", "2gis.com", "2gis.kz",
            "kinopoisk.ru", "rutube.ru", "boosty.to", "max.ru",
            "mts.ru", "beeline.ru", "megafon.ru", "tele2.ru", "t2.ru",
            "rzd.ru", "aeroflot.ru", "domclick.ru", "dns-shop.ru",
            "5ka.ru", "lemanapro.ru", "dodopizza.ru", "chizhik.club",
            "1c.ru", "bitrix24.ru", "gov.ru", "auto.ru", "banki.ru",
            "dom.ru", "dnevnik.ru", "dellin.ru", "yadro.ru",
            "mtalk.google.com", "push.apple.com", "api.push.apple.com",
        ],
        "DirectIp": [
            "87.240.128.0/18", "95.213.0.0/17", "93.186.224.0/21", "185.32.248.0/22",
            "217.20.144.0/20", "5.61.16.0/21", "185.16.244.0/22", "185.16.148.0/22",
            "17.0.0.0/8", "193.200.10.0/23", "91.223.63.0/24",
            "217.12.96.0/24", "217.12.97.0/24", "217.12.98.0/24", "217.12.99.0/24",
            "217.12.100.0/24", "217.12.101.0/24", "217.12.102.0/24", "217.12.103.0/24",
            "217.12.104.0/24", "217.12.105.0/24", "217.12.106.0/24", "217.12.110.0/24",
            "185.179.144.0/22", "195.242.82.0/23", "217.14.48.0/20",
            "46.226.122.0/24", "91.212.64.0/24", "91.223.93.0/24",
            "185.73.192.0/22", "195.34.20.0/23",
            "85.198.76.0/22", "91.230.107.0/24", "185.62.200.0/23",
            "185.138.252.0/22", "194.1.214.0/24", "213.184.155.0/24", "213.184.156.0/22",
            "176.114.120.0/21", "185.89.12.0/24", "185.89.14.0/23",
        ],
        "ProxySites": [],
        "ProxyIp": [],
        "BlockSites": [],
        "BlockIp": [],
    }
    routing_json = _json.dumps(happ_routing, ensure_ascii=False, separators=(',', ':'))
    routing_b64 = base64.b64encode(routing_json.encode()).decode()

    # Для всех клиентов (Nekobox, Happ etc.) - стандартный Base64 и заголовки
    headers = {
        "Subscription-Userinfo": f"upload={upload}; download={download}; total={total}; expire={expire}",
        "Profile-Title": "Reality VPN",
        "profile-update-interval": "2",
        "support-url": "https://t.me/reality_vpn_robot",
        "announce": "base64:4pqhINCd0LUg0YDQsNCx0L7RgtCw0LXRgiBWUE4/INCX0LDQudC00LjRgtC1INCyINCx0L7RgtCwIEByZWFsaXR5X3Zwbl9yb2JvdCDihpIg0JTQuNCw0LPQvdC+0YHRgtC40LrQsCDRgdC10YDQstC10YDQvtCyINC4INGB0LvQtdC00YPQudGC0LUg0LjQvdGB0YLRgNGD0LrRhtC40Y/QvCE=",
    }

    # Добавляем директивы в тело подписки для Happ
    # Routing передаётся только в теле через happ:// deep link (не через заголовки — они бывают слишком длинные)
    body_lines = [
        "#profile-update-interval: 2",
        "#support-url: https://t.me/reality_vpn_robot",
        "#announce: base64:4pqhINCd0LUg0YDQsNCx0L7RgtCw0LXRgiDQv9C+0LTQv9C40YHQutCwPyDQntCx0L3QvtCy0Lgg0LXRkSDQsiDQvdCw0YHRgtGA0L7QudC60LDRhSDQuNC70Lgg0L3QsNC20LzQuCDQutC90L7Qv9C60YMg0L7QsdC90L7QstC70LXQvdC40Y8h",
    ] + links
    content = base64.b64encode("\n".join(body_lines).encode()).decode()
    return Response(content=content, media_type="text/plain", headers=headers)