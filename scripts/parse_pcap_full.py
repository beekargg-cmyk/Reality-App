import struct, os, sys
from collections import Counter, defaultdict

# Find pcap file
pcap_file = None
for f in os.listdir(r'c:\Users\beeka\OneDrive\Desktop\Go'):
    if '2.pcap' in f:
        pcap_file = os.path.join(r'c:\Users\beeka\OneDrive\Desktop\Go', f)
        break

print(f'Файл: {os.path.basename(pcap_file)}')
print(f'Размер: {os.path.getsize(pcap_file)/1024/1024:.1f} MB')

with open(pcap_file, 'rb') as f:
    magic = f.read(4)
    endian = '<' if magic == b'\xd4\xc3\xb2\xa1' else '>'
    f.read(20)
    network = 1  # already know it's ethernet

    first_ts = None
    all_packets = []

    while True:
        hdr = f.read(16)
        if len(hdr) < 16: break
        ts_sec, ts_usec, incl_len, orig_len = struct.unpack(endian + 'IIII', hdr)
        data = f.read(incl_len)
        if len(data) < incl_len: break
        ts = ts_sec + ts_usec / 1e6
        if first_ts is None: first_ts = ts
        t = ts - first_ts

        off = 14
        if off >= len(data): continue
        if (data[off] >> 4) != 4 or len(data) <= off + 20: continue

        ihl = (data[off] & 0xF) * 4
        proto = data[off + 9]
        ttl = data[off + 8]
        src = '.'.join(str(b) for b in data[off+12:off+16])
        dst = '.'.join(str(b) for b in data[off+16:off+20])

        pkt = {'t': t, 'src': src, 'dst': dst, 'proto': proto, 'ttl': ttl, 'size': orig_len}

        if proto == 6 and len(data) > off + ihl + 13:
            sp = struct.unpack('!H', data[off+ihl:off+ihl+2])[0]
            dp = struct.unpack('!H', data[off+ihl+2:off+ihl+4])[0]
            flags = data[off+ihl+13]
            pkt['sp'] = sp
            pkt['dp'] = dp
            pkt['flags'] = flags
            pkt['type'] = 'TCP'

            # SNI
            tcp_hdr_len = ((data[off+ihl+12] >> 4) & 0xF) * 4
            ps = off + ihl + tcp_hdr_len
            if ps < len(data) - 10 and data[ps] == 0x16 and data[ps+1] == 0x03:
                if data[ps+5] == 0x01:
                    tls_data = data[ps:]
                    idx = 40
                    while idx < min(len(tls_data) - 10, 500):
                        if tls_data[idx] == 0x00 and tls_data[idx+1] == 0x00:
                            try:
                                sni_len = struct.unpack('!H', tls_data[idx+2:idx+4])[0]
                                if 5 < sni_len < 200 and tls_data[idx+6] == 0:
                                    nl = struct.unpack('!H', tls_data[idx+7:idx+9])[0]
                                    if nl < 200 and idx+9+nl <= len(tls_data):
                                        sni = tls_data[idx+9:idx+9+nl].decode('ascii', errors='replace')
                                        if '.' in sni and len(sni) > 3:
                                            pkt['sni'] = sni
                                            break
                            except: pass
                        idx += 1

        elif proto == 17 and len(data) > off + ihl + 8:
            sp = struct.unpack('!H', data[off+ihl:off+ihl+2])[0]
            dp = struct.unpack('!H', data[off+ihl+2:off+ihl+4])[0]
            pkt['sp'] = sp
            pkt['dp'] = dp
            pkt['type'] = 'UDP'

            udp_payload = data[off+ihl+8:]

            # DNS
            if dp == 53 or sp == 53:
                pkt['dns'] = True
                if len(udp_payload) > 12:
                    qc = struct.unpack('!H', udp_payload[4:6])[0]
                    if qc > 0:
                        pos = 12
                        labels = []
                        while pos < len(udp_payload) and udp_payload[pos] != 0:
                            ll = udp_payload[pos]
                            if ll > 63: break
                            pos += 1
                            if pos + ll <= len(udp_payload):
                                labels.append(udp_payload[pos:pos+ll].decode('ascii', errors='replace'))
                            pos += ll
                        pkt['dns_name'] = '.'.join(labels)

            # QUIC
            if dp == 443 or sp == 443:
                if len(udp_payload) > 5:
                    fb = udp_payload[0]
                    if fb & 0x80:
                        ver = '%02x%02x%02x%02x' % tuple(udp_payload[1:5])
                        pt = (fb & 0x30) >> 4
                        types = {0: 'INITIAL', 1: '0-RTT', 2: 'HANDSHAKE', 3: 'RETRY'}
                        pkt['quic'] = types.get(pt, 'LONG')
                        pkt['quic_ver'] = ver
                    elif fb & 0x40:
                        pkt['quic'] = '1-RTT'

        all_packets.append(pkt)

    duration = all_packets[-1]['t'] if all_packets else 0
    print(f'Всего пакетов: {len(all_packets)}, длительность: {duration:.0f}с ({duration/60:.1f} мин)')
    print()

    # ========= TIMELINE: разбиваем на 30-секундные окна =========
    print('=' * 70)
    print('  ХРОНОЛОГИЯ ТРАФИКА (окна по 30 секунд)')
    print('=' * 70)
    window = 30
    max_t = int(duration) + window
    for w_start in range(0, max_t, window):
        w_end = w_start + window
        wpkts = [p for p in all_packets if w_start <= p['t'] < w_end]
        if not wpkts: continue

        tcp_c = sum(1 for p in wpkts if p.get('type') == 'TCP')
        udp_c = sum(1 for p in wpkts if p.get('type') == 'UDP')
        quic_c = sum(1 for p in wpkts if 'quic' in p)
        rst_c = sum(1 for p in wpkts if p.get('type') == 'TCP' and p.get('flags', 0) & 0x04)
        syn_c = sum(1 for p in wpkts if p.get('type') == 'TCP' and p.get('flags', 0) & 0x02)
        dns_c = sum(1 for p in wpkts if p.get('dns'))
        total_bytes = sum(p['size'] for p in wpkts)

        # Key destinations
        dsts = Counter()
        for p in wpkts:
            remote = p['dst'] if p['src'].startswith('10.') else p['src']
            dsts[remote] += 1
        top3 = ', '.join(f'{ip}({c})' for ip, c in dsts.most_common(3))

        # SNIs
        snis = [p['sni'] for p in wpkts if 'sni' in p]
        sni_str = ', '.join(set(snis)) if snis else ''

        # DNS
        dns_names = [p.get('dns_name','') for p in wpkts if p.get('dns_name')]
        dns_str = ', '.join(list(dict.fromkeys(dns_names))[:3]) if dns_names else ''

        bar = '#' * min(len(wpkts) // 5, 40)
        print(f'[{w_start:4d}-{w_end:4d}s] {len(wpkts):4d} пкт ({total_bytes/1024:.0f}KB) '
              f'TCP={tcp_c} UDP={udp_c} QUIC={quic_c} SYN={syn_c} RST={rst_c} DNS={dns_c}')
        if top3: print(f'           Топ: {top3}')
        if sni_str: print(f'           SNI: {sni_str}')
        if dns_str: print(f'           DNS: {dns_str}')
        print()

    # ========= VPN PROXY SERVER DEEP DIVE =========
    print('=' * 70)
    print('  VPN/ПРОКСИ СЕРВЕР 85.137.252.97 — ДЕТАЛЬНЫЙ АНАЛИЗ')
    print('=' * 70)
    vpn_pkts = [p for p in all_packets if '85.137.252.97' in (p['src'], p['dst'])]
    if vpn_pkts:
        vpn_out = [p for p in vpn_pkts if p['dst'] == '85.137.252.97']
        vpn_in = [p for p in vpn_pkts if p['src'] == '85.137.252.97']
        vpn_bytes_out = sum(p['size'] for p in vpn_out)
        vpn_bytes_in = sum(p['size'] for p in vpn_in)
        vpn_ports = Counter(p.get('dp', 0) for p in vpn_out)

        print(f'  Пакетов к серверу:   {len(vpn_out)} ({vpn_bytes_out/1024:.0f} KB)')
        print(f'  Пакетов от сервера:  {len(vpn_in)} ({vpn_bytes_in/1024:.0f} KB)')
        print(f'  Порты: {dict(vpn_ports.most_common(5))}')
        print(f'  Первый пакет: {vpn_pkts[0]["t"]:.1f}s, Последний: {vpn_pkts[-1]["t"]:.1f}s')
        print(f'  Длительность сессии: {vpn_pkts[-1]["t"] - vpn_pkts[0]["t"]:.1f}s')

        # Check for gaps (disconnections)
        gaps = []
        for i in range(1, len(vpn_pkts)):
            gap = vpn_pkts[i]['t'] - vpn_pkts[i-1]['t']
            if gap > 5:
                gaps.append((vpn_pkts[i-1]['t'], vpn_pkts[i]['t'], gap))
        if gaps:
            print(f'  Разрывы (>5с):')
            for g in gaps[:10]:
                print(f'    [{g[0]:.1f}s - {g[1]:.1f}s] пауза {g[2]:.1f}с')
    print()

    # ========= QUIC DEEP DIVE =========
    print('=' * 70)
    print('  QUIC — ПОЛНЫЙ РАЗБОР')
    print('=' * 70)
    quic_pkts = [p for p in all_packets if 'quic' in p]
    if quic_pkts:
        # Group by connection (remote IP + local port)
        quic_conns = defaultdict(list)
        for p in quic_pkts:
            remote = p['dst'] if p['src'].startswith('10.') else p['src']
            quic_conns[remote].append(p)

        for remote_ip, pkts in sorted(quic_conns.items(), key=lambda x: -len(x[1])):
            initials = sum(1 for p in pkts if p.get('quic') == 'INITIAL')
            handshakes = sum(1 for p in pkts if p.get('quic') == 'HANDSHAKE')
            data_pkts = sum(1 for p in pkts if p.get('quic') == '1-RTT')
            retries = sum(1 for p in pkts if p.get('quic') == 'RETRY')
            total_b = sum(p['size'] for p in pkts)

            status = 'CONNECTED' if data_pkts > 0 else ('HANDSHAKING' if handshakes > 0 else 'BLOCKED?')

            print(f'  {remote_ip:22s} [{status}]')
            print(f'    Initial={initials} Handshake={handshakes} 1-RTT={data_pkts} Retry={retries} ({total_b/1024:.0f}KB)')
            print(f'    Время: {pkts[0]["t"]:.1f}s - {pkts[-1]["t"]:.1f}s')
            print()
    else:
        print('  Нет QUIC пакетов')

    # ========= CONNECTIONS THAT FAILED (RST) =========
    print('=' * 70)
    print('  ОБРЫВЫ СОЕДИНЕНИЙ (RST)')
    print('=' * 70)
    rst_pkts = [p for p in all_packets if p.get('type') == 'TCP' and p.get('flags', 0) & 0x04]
    rst_from_remote = [p for p in rst_pkts if not p['src'].startswith('10.') and not p['src'].startswith('192.168')]
    rst_from_client = [p for p in rst_pkts if p['src'].startswith('10.') or p['src'].startswith('192.168')]

    print(f'  RST от DPI/серверов: {len(rst_from_remote)}')
    print(f'  RST от клиента:     {len(rst_from_client)}')
    print()

    # RST target IPs grouped
    rst_targets = Counter()
    for r in rst_from_client:
        rst_targets[r['dst']] += 1
    for r in rst_from_remote:
        rst_targets[r['src']] += 1

    if rst_targets:
        print('  IP адреса с RST:')
        for ip, c in rst_targets.most_common(15):
            print(f'    {ip:22s}  {c} RST')
    print()

    # ========= UNIQUE EXTERNAL IPs =========
    print('=' * 70)
    print('  ВСЕ ВНЕШНИЕ IP (кто успешно отвечал)')
    print('=' * 70)
    responding_ips = Counter()
    for p in all_packets:
        if not p['src'].startswith('10.') and not p['src'].startswith('192.168') and not p['src'].startswith('239.') and not p['src'].startswith('224.'):
            responding_ips[p['src']] += 1

    for ip, c in responding_ips.most_common(30):
        proto_types = set()
        for p in all_packets:
            if p['src'] == ip or p['dst'] == ip:
                if 'quic' in p: proto_types.add('QUIC')
                elif p.get('type') == 'TCP': proto_types.add('TCP')
                elif p.get('type') == 'UDP': proto_types.add('UDP')
        protos = '+'.join(sorted(proto_types))
        print(f'  {ip:22s}  {c:4d} пкт  [{protos}]')
