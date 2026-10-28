#!/usr/bin/env python3
"""Fast VPN Pro 1.7.93 — 节点全量收割
实测接口: GET https://fastpro.fifavnet.net/cfg/{newuser,olduser,lowuser,vip}
零鉴权(x-token 可空) / 响应 AES-256-CBC 加密, key = MD5(LSB-of-fast.png 十六进制)
"""
import base64, hashlib, json, os, random, ssl, time
import urllib.request, urllib.error

HOST = 'https://fastpro.fifavnet.net'
PKG = 'com.fast.pro.smart.vpn'
CV = '1.7.93'
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nodes.json')


def lsb_md5_key(path):
    b = open(path, 'rb').read()
    n = len(b) - (len(b) % 4)
    hexs = ''
    for i in range(0, n, 4):
        nib = (b[i] & 1) << 3 | (b[i + 1] & 1) << 2 | (b[i + 2] & 1) << 1 | (b[i + 3] & 1)
        hexs += format(nib, 'x')
    return hashlib.md5(hexs.encode()).hexdigest()


KEY = lsb_md5_key(os.path.join(ASSETS, 'fast.png')).encode()
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=CTX))
HEADERS_BASE = {'User-Agent': 'okhttp/4.9.3', 'x-token': '', 'Accept': '*/*'}


def aes_dec(key, iv, data):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    c = Cipher(algorithms.AES(key), modes.CBC(iv.encode())).decryptor()
    out = c.update(data) + c.finalize()
    pad = out[-1]
    return out[:-pad] if 0 < pad <= 16 else out


def fetch(path, params, retries=3):
    url = HOST + path + '?' + '&'.join(f'{k}={v}' for k, v in params.items())
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS_BASE)
            r = OPENER.open(req, timeout=20)
            iv = r.headers.get('X-Yolo-Auth')
            body = r.read()
            if not iv:
                return {'ok': False, 'why': 'no-x-yolo-auth', 'raw': body[:200].decode('utf-8', 'replace')}
            return {'ok': True, 'json': json.loads(aes_dec(KEY, iv, base64.b64decode(body)).decode())}
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
        except Exception as e:
            last = repr(e)
        time.sleep(1)
    return {'ok': False, 'why': last}


def main():
    did = ''.join(random.choice('0123456789abcdef') for _ in range(16))
    # 参数空间: mcc 影响 limit_region 判定; lang/cv/pkg 可能影响下发池
    mcclist = ['310', '262', '440', '208', '724', '310', '234', '460']
    paths = ['/cfg/newuser', '/cfg/olduser', '/cfg/lowuser']
    groups = {}   # group_id -> group dict w/ servers
    stats = []
    for p in paths:
        for mcc in mcclist:
            params = {'did': did, 'mcc': mcc, 'mnc': '260', 'lang': 'en', 'cv': CV, 'pkg': PKG, 'os': 'Android'}
            res = fetch(p, params)
            if not res['ok']:
                stats.append({'path': p, 'mcc': mcc, 'fail': res.get('why')})
                continue
            data = res['json'].get('data') or {}
            sl = data.get('server_list') or []
            cnt = sum(len(g.get('servers') or []) for g in sl)
            stats.append({'path': p, 'mcc': mcc, 'groups': len(sl), 'servers': cnt,
                          'reconnect_time': data.get('reconnect_time')})
            for g in sl:
                gid = g.get('group_id') or g.get('iso_code')
                cur = groups.setdefault(gid, {'group_id': gid, 'iso_code': g.get('iso_code'),
                                              'desc': g.get('desc'), 'servers': {}})
                for s in g.get('servers') or []:
                    key = (s.get('server'), s.get('server_port'), s.get('password'))
                    cur['servers'][key] = s
    nodes = []
    for gid, g in groups.items():
        for s in g['servers'].values():
            nodes.append(dict(s, group_id=gid, group_desc=g['desc'], iso_code=g.get('iso_code')))
    uniq_ip = len({n['server'] for n in nodes})
    doc = {'harvested_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'host': HOST, 'did': did, 'groups': len(groups),
           'nodes': len(nodes), 'unique_ips': uniq_ip, 'stats': stats, 'node_list': nodes}
    json.dump(doc, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'groups={len(groups)} nodes={len(nodes)} unique_ips={uniq_ip} -> {OUT}')
    for s in stats:
        print(' ', s)


if __name__ == '__main__':
    main()
