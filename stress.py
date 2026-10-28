#!/usr/bin/env python3
"""Fast VPN Pro 节点压测: 裸 SOCKS5 -> 出口IP / 延迟 / 吞吐 / 并发
全部走 127.0.0.1 上 mihomo 的 listener 端口, 不读 HTTP_PROXY 环境变量(纯 socket)。
"""
import json, os, socket, ssl, struct, sys, time, statistics
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
TIMEOUT = 12


def socks5_connect(proxy_port, host, port, timeout=TIMEOUT):
    s = socket.create_connection(('127.0.0.1', proxy_port), timeout=timeout)
    s.settimeout(timeout)
    s.sendall(b'\x05\x01\x00')
    if s.recv(2) != b'\x05\x00':
        s.close(); raise OSError('socks handshake rejected')
    hb = host.encode()
    req = b'\x05\x01\x00\x03' + bytes([len(hb)]) + hb + struct.pack('>H', port)
    s.sendall(req)
    rep = s.recv(4)
    if len(rep) < 2 or rep[1] != 0:
        s.close(); raise OSError(f'socks connect failed rep={rep[1] if len(rep) > 1 else "?"}')
    atyp = rep[3]
    if atyp == 1:
        s.recv(4 + 2)
    elif atyp == 3:
        ln = s.recv(1)[0]; s.recv(ln + 2)
    elif atyp == 4:
        s.recv(16 + 2)
    return s


def http_get_via_socks(proxy_port, host, port, path='/', use_tls=False, extra_budget=None):
    s = socks5_connect(proxy_port, host, port)
    try:
        if use_tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            s = ctx.wrap_socket(s, server_hostname=host)
        req = (f'GET {path} HTTP/1.1\r\nHost: {host}\r\n'
               f'Connection: close\r\nUser-Agent: curl/8\r\nAccept: */*\r\n\r\n')
        s.sendall(req.encode())
        buf = b''
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            if extra_budget and len(buf) >= extra_budget:
                break
        return buf
    finally:
        try:
            s.close()
        except Exception:
            pass


def probe_one(pm):
    out = dict(pm)
    # 1) 裸 HTTP -> ip-api (真实出口 IP)
    t0 = time.time()
    try:
        raw = http_get_via_socks(pm['socks_port'], 'ip-api.com', 80,
                                 '/json/?fields=status,country,city,isp,query,as')
        dt = (time.time() - t0) * 1000
        body = raw.split(b'\r\n\r\n', 1)[-1].decode('utf-8', 'replace')
        j = json.loads(body)
        out.update({'http_ms': round(dt, 1), 'exit_ip': j.get('query'),
                    'exit_country': j.get('country'), 'exit_city': j.get('city'),
                    'exit_isp': j.get('isp'), 'exit_as': j.get('as')})
        out['ok'] = j.get('status') == 'success'
    except Exception as e:
        out.update({'ok': False, 'http_err': repr(e)[:120]})
        return out
    # 2) HTTPS 真实路径 (cloudflare trace)
    try:
        t0 = time.time()
        raw = http_get_via_socks(pm['socks_port'], 'www.cloudflare.com', 443,
                                 '/cdn-cgi/trace', use_tls=True)
        out['https_ms'] = round((time.time() - t0) * 1000, 1)
        txt = raw.split(b'\r\n\r\n', 1)[-1].decode('utf-8', 'replace')
        for line in txt.splitlines():
            if line.startswith('ip='):
                out['https_ip'] = line[3:]
            if line.startswith('loc='):
                out['https_loc'] = line[4:]
    except Exception as e:
        out['https_err'] = repr(e)[:120]
    # 3) 吞吐: 拉 2MB from a speed endpoint (HTTP, ipv4)
    try:
        t0 = time.time()
        raw = http_get_via_socks(pm['socks_port'], 'speed.cloudflare.com', 80,
                                 '/__down?bytes=2000000')
        dt = time.time() - t0
        body_len = len(raw.split(b'\r\n\r\n', 1)[-1])
        out['dl_mbps'] = round(body_len * 8 / dt / 1e6, 2) if dt > 0 else 0
    except Exception as e:
        out['dl_err'] = repr(e)[:80]
    return out


def main():
    portmap = json.load(open(os.path.join(HERE, 'portmap.json'), encoding='utf-8'))['portmap']
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(portmap)
    pms = portmap[:limit]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=min(25, len(pms))) as ex:
        results = list(ex.map(probe_one, pms))
    elapsed = time.time() - t0
    alive = [r for r in results if r.get('ok')]
    print(f'\n=== 单节点压测: {len(results)} 探 / 存活 {len(alive)} / 耗时 {elapsed:.1f}s ===')
    for r in sorted(results, key=lambda x: (not x.get('ok'), x.get('http_ms') or 9e9)):
        flag = 'OK  ' if r.get('ok') else 'FAIL'
        print(f"{flag} :{r['socks_port']} {str(r.get('iso')):2s} {r['server']:16s} "
              f"ms={r.get('http_ms')} exit={r.get('exit_ip')} {r.get('exit_country')}/"
              f"{r.get('exit_isp')} https={r.get('https_ms')} dl={r.get('dl_mbps')}Mbps "
              f"{r.get('http_err','')}{r.get('https_err','')}")
    if alive:
        ms = [r['http_ms'] for r in alive if r.get('http_ms')]
        dl = [r['dl_mbps'] for r in alive if r.get('dl_mbps')]
        print(f"\n延迟 P50={statistics.median(ms):.0f}ms min={min(ms):.0f} max={max(ms):.0f}")
        if dl:
            print(f"吞吐 P50={statistics.median(dl):.2f}Mbps min={min(dl):.2f} max={max(dl):.2f}")
        print('出口 IP 与节点 IP 一致:', sum(1 for r in alive if r.get('exit_ip') == r['server']), '/', len(alive))
    json.dump({'tested_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'elapsed_s': round(elapsed, 1),
               'total': len(results), 'alive': len(alive), 'results': results},
              open(os.path.join(HERE, 'stress_result.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('-> stress_result.json')


if __name__ == '__main__':
    main()
