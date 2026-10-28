#!/usr/bin/env python3
"""Fast VPN Pro 1.7.93 — /cfg/* 最小探针
配置与密钥全部从 assets 读取, 脚本内不含任何硬编码凭证:
    assets/http_yolo_config.json  -> hostUrl / headerXToken / hmacMd5Key
    assets/fast.png               -> business AES-256 key (PNG LSB 派生)
    assets/api_yolobase_net.png    -> common  AES-256 key

协议:
    GET  {host}{path}?did&mcc&mnc&lang&cv&pkg&os      header x-token
    响应 header X-Yolo-Auth = IV(16), body = base64(AES-256-CBC/PKCS5(json)); 无该头则明文
"""
import base64
import hashlib
import json
import os
import random
import ssl
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, 'assets')
PKG = 'com.fast.pro.smart.vpn'
CV = '1.7.93'


def lsb_md5_key(path):
    b = open(path, 'rb').read()
    n = len(b) - (len(b) % 4)
    hexs = ''
    for i in range(0, n, 4):
        hexs += format((b[i] & 1) << 3 | (b[i + 1] & 1) << 2
                       | (b[i + 2] & 1) << 1 | (b[i + 3] & 1), 'x')
    return hashlib.md5(hexs.encode()).hexdigest()


def load_config():
    cfg = json.load(open(os.path.join(ASSETS, 'http_yolo_config.json'), encoding='utf-8'))
    b, c = cfg['http_business'], cfg['http_common']
    return {
        'host': b['hostUrl'] or c['hostUrl'],
        'x_token': b['headerXToken'],          # business 侧通常为空串
        'hmac_key': b['hmacMd5Key'],
        'key': lsb_md5_key(os.path.join(ASSETS, b['assetsResXTokenName'])).encode(),
        'x_token_common': c['headerXToken'],
        'key_common': lsb_md5_key(os.path.join(ASSETS, c['assetsResXTokenName'])).encode(),
    }


def aes_dec(key, iv, data):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    c = Cipher(algorithms.AES(key), modes.CBC(iv.encode())).decryptor()
    out = c.update(data) + c.finalize()
    pad = out[-1]
    return out[:-pad] if 0 < pad <= 16 else out


CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
# 必须绕开环境里的 HTTP_PROXY, 否则测出来的是代理的行为
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                     urllib.request.HTTPSHandler(context=CTX))


def rand_did(n=16):
    return ''.join(random.choice('0123456789abcdef') for _ in range(n))


def probe(cfg, path, xtoken, key, extra=None, timeout=20, did=None):
    did = did or rand_did()
    q = {'did': did, 'mcc': '310', 'mnc': '260', 'lang': 'en',
         'cv': CV, 'pkg': PKG, 'os': 'Android'}
    # 注意: mcc 460/461/432/467 会命中 limit_region, 换 310(US) 避免干扰
    if extra:
        q.update(extra)
    url = cfg['host'] + path + '?' + '&'.join('%s=%s' % kv for kv in q.items())
    req = urllib.request.Request(url, headers={'x-token': xtoken, 'User-Agent': 'okhttp/4.9.3'})
    try:
        r = OPENER.open(req, timeout=timeout)
        status, hdrs, body = r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        status, hdrs, body = e.code, dict(e.headers), e.read()
    except Exception as e:
        return {'url': url, 'error': repr(e)}
    res = {'url': url, 'status': status, 'len': len(body)}
    iv = hdrs.get('X-Yolo-Auth') or hdrs.get('x-yolo-auth')
    if iv and iv.strip():
        try:
            res['plain'] = aes_dec(key, iv.strip(), base64.b64decode(body)).decode('utf-8', 'replace')
        except Exception as e:
            res['dec_err'] = repr(e)
            res['raw'] = body[:200].decode('utf-8', 'replace')
    else:
        res['raw'] = body[:400].decode('utf-8', 'replace')
    return res


if __name__ == '__main__':
    cfg = load_config()
    print('host      =', cfg['host'])
    print('business  =', cfg['key'].decode())
    print('common    =', cfg['key_common'].decode())
    did = rand_did()
    for path, xt, k in [('/cfg/newuser', cfg['x_token'], cfg['key']),
                        ('/cfg/olduser', cfg['x_token'], cfg['key']),
                        ('/cfg/lowuser', cfg['x_token'], cfg['key']),
                        ('/cfg/vip', cfg['x_token'], cfg['key'])]:
        r = probe(cfg, path, xt, k, did=did)
        print('\n===', path, '===')
        print(json.dumps(r, ensure_ascii=False, indent=1)[:1200])
