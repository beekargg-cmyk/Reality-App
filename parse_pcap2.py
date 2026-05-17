import struct, os, sys
from collections import Counter, defaultdict

# Find pcap file
pcap_file = None
for f in os.listdir(r'c:\Users\beeka\OneDrive\Desktop\Go'):
    if '2.pcap' in f:
        pcap_file = os.path.join(r'c:\Users\beeka\OneDrive\Desktop\Go', f)
        break

if not pcap_file:
    print("PCAP файл не найден!")
    sys.exit(1)

print(f'Файл: {os.path.basename(pcap_file)}')
print(f'Размер: {os.path.getsize(pcap_file)} байт ({os.path.getsize(pcap_file)/1024/1024:.1f} MB)')
print()

with open(pcap_file, 'rb') as f:
    magic = f.read(4)
    endian = '<' if magic == b'\xd4\xc3\xb2\xa1' else '>'
    ver_major, ver_minor, tz, sigfigs, snaplen, network = struct.unpack(endian + 'HHiIII', f.read(20))
    print(f'Link type: {network}')

    first_ts = None
    total = 0
    tcp_count = 0
    udp_count = 0
    rst_count = 0
    syn_count = 0
    
    # QUIC tracking
    quic_packets = []
    quic_ips = Counter()
    quic_initial_count = 0
    
    # DNS
    dns_queries = []
    
    # RST details
    rst_details = []
    
    # IP tracking
    dst_counter = Counter()
    src_counter = Counter()
    
    # Protocol tracking
    udp_port_counter = Counter()
    tcp_port_counter = Counter()
    
    # Per-IP traffic volume
    ip_bytes = Counter()
    
    # TLS SNI tracking
    sni_list = []
    
    # Successful vs failed connections per IP
    ip_syn = Counter()
    ip_rst = Counter()
    ip_established = Counter()

    while True:
        hdr = f.read(16)
        if len(hdr) < 16: break
        ts_sec, ts_usec, incl_len, orig_len = struct.unpack(endian + 'IIII', hdr)
        data = f.read(incl_len)
        if len(data) < incl_len: break
        
        ts = ts_sec + ts_usec / 1e6
        if first_ts is None: first_ts = ts
        total += 1

        # IP offset
        off = 14 if network == 1 else 0
        if off >= len(data): continue
        if (data[off] >> 4) != 4 or len(data) <= off + 20: continue

        ihl = (data[off] & 0xF) * 4
        proto = data[off + 9]
        ttl = data[off + 8]
        total_len = struct.unpack('!H', data[off+2:off+4])[0]
        src = '.'.join(str(b) for b in data[off+12:off+16])
        dst = '.'.join(str(b) for b in data[off+16:off+20])
        
        dst_counter[dst] += 1
        ip_bytes[dst] += orig_len

        if proto == 6 and len(data) > off + ihl + 13:  # TCP
            tcp_count += 1
            sp = struct.unpack('!H', data[off+ihl:off+ihl+2])[0]
            dp = struct.unpack('!H', data[off+ihl+2:off+ihl+4])[0]
            flags = data[off+ihl+13]
            tcp_port_counter[dp] += 1
            
            if flags & 0x02:  # SYN
                syn_count += 1
                ip_syn[dst] += 1
            if flags & 0x04:  # RST
                rst_count += 1
                ip_rst[src if src != '10.' else dst] += 1
                t = ts - first_ts
                rst_details.append({
                    'time': t, 'src': src, 'sp': sp,
                    'dst': dst, 'dp': dp, 'ttl': ttl, 'size': orig_len
                })
            if flags == 0x10:  # Pure ACK (established)
                ip_established[dst] += 1
            
            # TLS SNI extraction
            tcp_hdr_len = ((data[off+ihl+12] >> 4) & 0xF) * 4
            payload_start = off + ihl + tcp_hdr_len
            if payload_start < len(data) - 10:
                if data[payload_start] == 0x16 and data[payload_start+1] == 0x03:
                    if len(data) > payload_start + 5 and data[payload_start+5] == 0x01:
                        # Extract SNI
                        tls_data = data[payload_start:]
                        idx = 0
                        while idx < len(tls_data) - 10 and idx < 500:
                            if tls_data[idx] == 0x00 and tls_data[idx+1] == 0x00 and idx > 40:
                                try:
                                    sni_len_outer = struct.unpack('!H', tls_data[idx+2:idx+4])[0]
                                    if 5 < sni_len_outer < 200:
                                        sni_type = tls_data[idx+6]
                                        if sni_type == 0:
                                            name_len = struct.unpack('!H', tls_data[idx+7:idx+9])[0]
                                            if name_len < 200 and idx+9+name_len <= len(tls_data):
                                                sni = tls_data[idx+9:idx+9+name_len].decode('ascii', errors='replace')
                                                if '.' in sni and len(sni) > 3:
                                                    sni_list.append((ts - first_ts, src, dst, dp, sni))
                                                    break
                                except: pass
                            idx += 1

        elif proto == 17 and len(data) > off + ihl + 8:  # UDP
            udp_count += 1
            sp = struct.unpack('!H', data[off+ihl:off+ihl+2])[0]
            dp = struct.unpack('!H', data[off+ihl+2:off+ihl+4])[0]
            udp_len = struct.unpack('!H', data[off+ihl+4:off+ihl+6])[0]
            udp_port_counter[dp] += 1
            
            udp_payload = data[off+ihl+8:]
            
            # DNS
            if dp == 53 or sp == 53:
                if len(udp_payload) > 12:
                    qcount = struct.unpack('!H', udp_payload[4:6])[0]
                    if qcount > 0:
                        pos = 12
                        labels = []
                        while pos < len(udp_payload) and udp_payload[pos] != 0:
                            llen = udp_payload[pos]
                            if llen > 63: break
                            pos += 1
                            if pos + llen <= len(udp_payload):
                                labels.append(udp_payload[pos:pos+llen].decode('ascii', errors='replace'))
                            pos += llen
                        domain = '.'.join(labels)
                        if domain and domain not in dns_queries:
                            dns_queries.append(domain)
            
            # QUIC detection
            # QUIC packets go to port 443 (usually) and have specific header format
            # Long header: first bit = 1 (0x80+), then version
            # Short header: first bit = 0
            is_quic = False
            quic_type = ""
            quic_version = ""
            
            if dp == 443 or sp == 443 or dp == 8443 or sp == 8443:
                if len(udp_payload) > 5:
                    first_byte = udp_payload[0]
                    
                    # QUIC Long Header (Initial, Handshake, 0-RTT, Retry)
                    if first_byte & 0x80:  # Long header
                        is_quic = True
                        ver_bytes = udp_payload[1:5]
                        quic_version = '%02x%02x%02x%02x' % (ver_bytes[0], ver_bytes[1], ver_bytes[2], ver_bytes[3])
                        
                        pkt_type = (first_byte & 0x30) >> 4
                        if quic_version == '00000001':  # QUIC v1
                            if pkt_type == 0: quic_type = "INITIAL"
                            elif pkt_type == 1: quic_type = "0-RTT"
                            elif pkt_type == 2: quic_type = "HANDSHAKE"
                            elif pkt_type == 3: quic_type = "RETRY"
                        elif quic_version == '6b3343cf':  # QUIC v2
                            quic_type = "QUICv2"
                        elif quic_version == '00000000':
                            quic_type = "VERSION_NEG"
                        else:
                            quic_type = "LONG_HDR"
                        
                        if pkt_type == 0:  # Initial
                            quic_initial_count += 1
                    
                    elif first_byte & 0x40:  # Short header (1-RTT data)
                        is_quic = True
                        quic_type = "SHORT(1-RTT)"
                        quic_version = "n/a"
            
            if is_quic:
                t = ts - first_ts
                direction = "OUT" if not src.startswith('10.') and not src.startswith('192.168') else "OUT"
                if not dst.startswith('10.') and not dst.startswith('192.168'):
                    direction = "OUT"
                else:
                    direction = "IN"
                    
                quic_packets.append({
                    'time': t, 'src': src, 'sp': sp,
                    'dst': dst, 'dp': dp, 'type': quic_type,
                    'version': quic_version, 'size': orig_len,
                    'ttl': ttl, 'direction': direction
                })
                remote_ip = dst if direction == "OUT" else src
                quic_ips[remote_ip] += 1

    # ===================== PRINT RESULTS =====================
    duration = (ts - first_ts) if first_ts else 0
    
    print()
    print('=' * 60)
    print('              ПОЛНЫЙ АНАЛИЗ PCAP')
    print('=' * 60)
    print(f'Всего пакетов:        {total}')
    print(f'TCP:                  {tcp_count}')
    print(f'UDP:                  {udp_count}')
    print(f'SYN (новые TCP):      {syn_count}')
    print(f'RST (сбросы):         {rst_count}')
    print(f'Длительность:         {duration:.1f} сек ({duration/60:.1f} мин)')
    print()
    
    # === QUIC ===
    print('=' * 60)
    print('              QUIC ТРАФИК')
    print('=' * 60)
    print(f'QUIC пакетов всего:   {len(quic_packets)}')
    print(f'QUIC Initial:         {quic_initial_count}')
    print()
    
    if quic_packets:
        # Group by remote IP
        print('--- QUIC по IP адресам ---')
        for ip, count in quic_ips.most_common(20):
            print(f'  {ip:22s}  {count} пакетов')
        print()
        
        # Show QUIC packet details (first 50)
        print('--- Детали QUIC пакетов (первые 50) ---')
        for q in quic_packets[:50]:
            line = '  [%.3fs] %s:%d -> %s:%d  %s  ver=%s  size=%d  TTL=%d' % (
                q['time'], q['src'], q['sp'], q['dst'], q['dp'],
                q['type'], q['version'], q['size'], q['ttl']
            )
            print(line)
        if len(quic_packets) > 50:
            print(f'  ... и ещё {len(quic_packets) - 50} QUIC пакетов')
        print()
        
        # QUIC type breakdown
        type_counter = Counter(q['type'] for q in quic_packets)
        print('--- QUIC по типам ---')
        for t, c in type_counter.most_common():
            print(f'  {t:20s}  {c} пакетов')
    else:
        print('  (QUIC пакеты не обнаружены)')
    print()
    
    # === TOP IPs ===
    print('=' * 60)
    print('              ТОП IP АДРЕСОВ')
    print('=' * 60)
    print('--- По количеству пакетов ---')
    for ip, count in dst_counter.most_common(20):
        bytes_kb = ip_bytes[ip] / 1024
        print(f'  {ip:22s}  {count:5d} пкт  ({bytes_kb:.0f} KB)')
    print()
    
    # === DNS ===
    print('=' * 60)
    print('              DNS ЗАПРОСЫ')
    print('=' * 60)
    for d in dns_queries[:40]:
        print(f'  {d}')
    if not dns_queries:
        print('  (нет DNS в дампе)')
    print()
    
    # === TLS SNI ===
    print('=' * 60)
    print('              TLS SNI (ClientHello)')
    print('=' * 60)
    sni_counter = Counter(s[4] for s in sni_list)
    for sni, count in sni_counter.most_common(30):
        print(f'  {sni:40s}  {count} соед.')
    if not sni_list:
        print('  (нет TLS ClientHello)')
    print()
    
    # === UDP ports ===
    print('=' * 60)
    print('              UDP ПОРТЫ (Топ-10)')
    print('=' * 60)
    for port, count in udp_port_counter.most_common(10):
        print(f'  :{port:5d}   {count} пакетов')
    print()
    
    # === RST ===
    print('=' * 60)
    print('              RST ПАКЕТЫ ({})'.format(rst_count))
    print('=' * 60)
    if rst_details:
        # Group RSTs by source
        rst_from_client = [r for r in rst_details if r['src'].startswith('10.') or r['src'].startswith('192.168')]
        rst_from_remote = [r for r in rst_details if not r['src'].startswith('10.') and not r['src'].startswith('192.168')]
        
        print(f'  RST ОТ клиента:    {len(rst_from_client)}')
        print(f'  RST ОТ сервера/DPI: {len(rst_from_remote)}')
        print()
        
        if rst_from_remote:
            print('--- RST от серверов/DPI (первые 20) ---')
            for r in rst_from_remote[:20]:
                line = '  [%.3fs] %s:%d -> %s:%d RST TTL=%d size=%d' % (
                    r['time'], r['src'], r['sp'], r['dst'], r['dp'], r['ttl'], r['size']
                )
                print(line)
            print()
        
        if rst_from_client:
            print('--- RST от клиента (первые 20) ---')
            for r in rst_from_client[:20]:
                line = '  [%.3fs] %s:%d -> %s:%d RST TTL=%d size=%d' % (
                    r['time'], r['src'], r['sp'], r['dst'], r['dp'], r['ttl'], r['size']
                )
                print(line)
    else:
        print('  RST пакетов нет!')
