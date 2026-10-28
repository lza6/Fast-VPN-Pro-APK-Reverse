#!/usr/bin/env python3
"""Fast VPN Pro — 节点池 demo server
端口: 8955
接口:
  GET /                demo 页面
  GET /api/nodes       节点清单 + 最近一次测活快照
  GET /api/summary     池子统计
  GET /api/probe?ip=   实时单节点探测(经 mihomo listener, 若在跑)
  GET /api/harvest     重新拉取云端节点列表(实跑, 证明链路)
  GET /api/proxies     new-api 可直接吃的 socks5 清单(纯文本)
"""
import hashlib, json, os, select, socket, ssl, struct, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('DEMO_PORT', 8955))


def load(name, default=None):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        return default
    return json.load(open(p, encoding='utf-8'))


def snapshot():
    nodes = load('nodes.json', {'node_list': []})
    stress = load('stress_result.json', {})
    pm = {p['server']: p for p in (load('portmap.json', {}) or {}).get('portmap', [])}
    by_ip = {r['server']: r for r in stress.get('results', [])}
    out = []
    for n in nodes.get('node_list', []):
        s = by_ip.get(n['server'], {})
        out.append({
            'name': n.get('name'), 'server': n['server'], 'port': n['server_port'],
            'method': n.get('method'), 'iso': n.get('iso_code'), 'city': n.get('city'),
            'isp': n.get('isp'), 'group': n.get('group_desc'),
            'socks_port': (pm.get(n['server']) or {}).get('socks_port'),
            'alive': bool(s.get('ok')),
            'exit_ip': s.get('exit_ip'), 'exit_isp': s.get('exit_isp'),
            'http_ms': s.get('http_ms'), 'https_ms': s.get('https_ms'),
            'dl_mbps': s.get('dl_mbps'), 'err': s.get('http_err'),
        })
    return out


class H(BaseHTTPRequestHandler):
    server_version = 'fastvpn-demo/1.0'

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, indent=1)
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == '/':
            p = os.path.join(HERE, 'demo.html')
            if os.path.exists(p):
                return self._send(200, open(p, 'rb').read(), 'text/html; charset=utf-8')
            return self._send(404, {'error': 'demo.html missing'})
        if u.path == '/api/nodes':
            return self._send(200, {'nodes': snapshot()})
        if u.path == '/api/summary':
            ns = snapshot()
            alive = [n for n in ns if n['alive']]
            lat = sorted(n['http_ms'] for n in alive if n.get('http_ms'))
            return self._send(200, {
                'total': len(ns), 'alive': len(alive),
                'countries': sorted({n['iso'] for n in alive}),
                'latency_p50_ms': round(lat[len(lat) // 2]) if lat else None,
                'harvested_at': load('nodes.json', {}).get('harvested_at'),
                'tested_at': load('stress_result.json', {}).get('tested_at'),
                'data_source': 'fastpro.fifavnet.net /cfg/newuser (AES-256-CBC, zero-auth)',
            })
        if u.path == '/api/harvest':
            import harvest
            before = load('nodes.json', {}).get('nodes')
            params = {'did': ''.join(hashlib.md5(os.urandom(8)).hexdigest()[:16]),
                      'mcc': '310', 'mnc': '260', 'lang': 'en',
                      'cv': harvest.CV, 'pkg': harvest.PKG, 'os': 'Android'}
            r = harvest.fetch('/cfg/newuser', params)
            if not r['ok']:
                return self._send(502, {'ok': False, 'why': r.get('why')})
            sl = (r['json'].get('data') or {}).get('server_list') or []
            got = sum(len(g.get('servers') or []) for g in sl)
            return self._send(200, {'ok': True, 'fetched': got,
                                    'cached_in_nodes_json': before,
                                    'first': (sl[0]['servers'][0] if sl else None)})
        if u.path == '/api/probe':
            ip = (q.get('ip') or [''])[0]
            pm = {p['server']: p for p in (load('portmap.json', {}) or {}).get('portmap', [])}
            port = (pm.get(ip) or {}).get('socks_port')
            if not port:
                return self._send(404, {'error': 'no listener for %s (需要先跑 build_mihomo + mihomo)' % ip})
            try:
                import stress
                t0 = time.time()
                raw = stress.http_get_via_socks(port, 'ip-api.com', 80, '/json/?fields=query,country,isp')
                body = raw.split(b'\r\n\r\n', 1)[-1].decode('utf-8', 'replace')
                return self._send(200, {'ok': True, 'ms': round((time.time() - t0) * 1000),
                                        'exit': json.loads(body)})
            except Exception as e:
                return self._send(200, {'ok': False, 'err': repr(e)[:200]})
        if u.path == '/api/proxies':
            ns = [n for n in snapshot() if n['alive'] and n.get('socks_port')]
            txt = '# fast-vpn-pro alive proxies (%s)\n' % time.strftime('%Y-%m-%d %H:%M:%S')
            txt += '\n'.join('socks5://127.0.0.1:%d' % n['socks_port'] for n in ns) + '\n'
            return self._send(200, txt, 'text/plain; charset=utf-8')
        return self._send(404, {'error': 'not found'})

    def log_message(self, fmt, *a):
        pass


if __name__ == '__main__':
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), H)
    print(f'demo: http://127.0.0.1:{PORT}/  (nodes/api/summary/probe/harvest/proxies)')
    srv.serve_forever()
