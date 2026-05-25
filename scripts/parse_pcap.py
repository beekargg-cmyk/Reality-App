import struct, sys, os
from collections import Counter

# Find pcap file
pcap_file = None
for f in os.listdir(r'c:\Users\beeka\OneDrive\Desktop\Go'):
    if f.endswith('.pcap'):
        pcap_file = os.path.join(r'c:\Users\beeka\OneDrive\Desktop\Go', f)
        break

if not pcap_file:
    print("PCAP файл не найден!")
    sys.exit(1)

print(f'Файл: {pcap_file}')
print(f'Размер: {os.path.getsize(pcap_file)} байт')
print()

with open(pcap_file, 'rb') as f:
    magic = f.read(4)
    if magic == b'\xd4\xc3\xb2\xa1':
        endian = '<'
        print('Формат: PCAP (Little Endian)')
    elif magic == b'\xa1\xb2\xc3\xd4':
        endian = '>'
        print('Формат: PCAP (Big Endian)')
    else:
        print(f'Magic: {magic.hex()} - неизвестный формат')
        sys.exit(1)

    ver_major, ver_minor, tz, sigfigs, snaplen, network = struct.unpack(endian + 'HHiIII', f.read(20))
    print(f'Версия: {ver_major}.{ver_minor}, Link type: {network}')
    print()

    packets = []
    tcp_count = 0
    udp_count = 0
    rst_count = 0
    syn_count = 0
    unique_ips = set()
    dns_queries = []
    tls_hello_count = 0
    rst_details = []

    while True:
        hdr = f.read(16)
        if len(hdr) < 16:
            break
        ts_sec, ts_usec, incl_len, orig_len = struct.unpack(endian + 'IIII', hdr)
        data = f.read(incl_len)
        if len(data) < incl_len:
            break

        packets.append({'ts': ts_sec + ts_usec / 1e6, 'len': orig_len, 'data': data})

        # Determine IP offset
        offset = 0
        if network == 1:
            offset = 14
        elif network in (228, 101):
            offset = 0

        if offset >= len(data):
            continue

        ip_ver = (data[offset] >> 4) & 0xF
        if ip_ver != 4 or len(data) <= offset + 20:
            continue

        ihl = (data[offset] & 0xF) * 4
        proto = data[offset + 9]
        ttl = data[offset + 8]
        src_ip = '.'.join(str(b) for b in data[offset + 12:offset + 16])
        dst_ip = '.'.join(str(b) for b in data[offset + 16:offset + 20])
        unique_ips.add(src_ip)
        unique_ips.add(dst_ip)

        if proto == 6 and len(data) > offset + ihl + 13:  # TCP
            tcp_count += 1
            src_port = struct.unpack('!H', data[offset + ihl:offset + ihl + 2])[0]
            dst_port = struct.unpack('!H', data[offset + ihl + 2:offset + ihl + 4])[0]
            flags = data[offset + ihl + 13]

            if flags & 0x04:
                rst_count += 1
                t = packets[-1]['ts'] - packets[0]['ts'] if len(packets) > 1 else 0
                rst_details.append({
                    'time': t,
                    'src': src_ip,
                    'sp': src_port,
                    'dst': dst_ip,
                    'dp': dst_port,
                    'ttl': ttl,
                    'size': orig_len
                })
            if flags & 0x02:
                syn_count += 1

            # TLS ClientHello check
            tcp_hdr_len = ((data[offset + ihl + 12] >> 4) & 0xF) * 4
            payload_start = offset + ihl + tcp_hdr_len
            if payload_start < len(data) - 5:
                if data[payload_start] == 0x16 and data[payload_start + 1] == 0x03:
                    if data[payload_start + 5] == 0x01:
                        tls_hello_count += 1

        elif proto == 17 and len(data) > offset + ihl + 8:  # UDP
            udp_count += 1
            src_port = struct.unpack('!H', data[offset + ihl:offset + ihl + 2])[0]
            dst_port = struct.unpack('!H', data[offset + ihl + 2:offset + ihl + 4])[0]

            if dst_port == 53 or src_port == 53:
                dns_data = data[offset + ihl + 8:]
                if len(dns_data) > 12:
                    qcount = struct.unpack('!H', dns_data[4:6])[0]
                    if qcount > 0:
                        pos = 12
                        labels = []
                        while pos < len(dns_data) and dns_data[pos] != 0:
                            llen = dns_data[pos]
                            if llen > 63:
                                break
                            pos += 1
                            if pos + llen <= len(dns_data):
                                labels.append(dns_data[pos:pos + llen].decode('ascii', errors='replace'))
                            pos += llen
                        domain = '.'.join(labels)
                        if domain and domain not in dns_queries:
                            dns_queries.append(domain)

    # === PRINT RESULTS ===
    print('=' * 50)
    print('           СВОДКА PCAP ФАЙЛА')
    print('=' * 50)
    print(f'Всего пакетов:       {len(packets)}')
    print(f'TCP пакетов:         {tcp_count}')
    print(f'UDP пакетов:         {udp_count}')
    print(f'SYN (новые соед.):   {syn_count}')
    print(f'TLS ClientHello:     {tls_hello_count}')
    print(f'Уникальных IP:       {len(unique_ips)}')
    print()

    if rst_count > 0:
        print(f'!!! ОБНАРУЖЕНО {rst_count} RST ПАКЕТОВ !!!')
    else:
        print('RST пакетов: 0 (Провайдер НЕ инжектит сбросы)')
    print()

    if len(packets) > 1:
        duration = packets[-1]['ts'] - packets[0]['ts']
        print(f'Длительность записи: {duration:.1f} сек')
    print()

    # Top destination IPs
    ip_counter = Counter()
    for p in packets:
        d = p['data']
        off = 0 if network in (228, 101) else 14
        if len(d) > off + 20:
            v = (d[off] >> 4) & 0xF
            if v == 4:
                dst = '.'.join(str(b) for b in d[off + 16:off + 20])
                ip_counter[dst] += 1

    print('--- Топ-15 IP назначения ---')
    for ip, count in ip_counter.most_common(15):
        print(f'  {ip:22s}  {count} пакетов')
    print()

    print('--- DNS запросы ---')
    if dns_queries:
        for d in dns_queries[:30]:
            print(f'  {d}')
    else:
        print('  (нет DNS запросов в дампе)')
    print()

    # RST details
    if rst_details:
        print('--- ДЕТАЛИ RST ПАКЕТОВ ---')
        for r in rst_details[:30]:
            line = '  [%.3fs] %s:%d -> %s:%d RST (TTL=%d, size=%d)' % (
                r['time'], r['src'], r['sp'], r['dst'], r['dp'], r['ttl'], r['size']
            )
            print(line)
        if len(rst_details) > 30:
            print(f'  ... и ещё {len(rst_details) - 30} RST')
