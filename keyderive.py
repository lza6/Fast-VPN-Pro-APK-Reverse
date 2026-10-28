#!/usr/bin/env python3
"""派生 Fast VPN Pro 的 AES-256 key, 并可选解密内置兜底节点表。

算法(逆向自 com.yolo.networklibrary.common.util.cipher.RepositoryCipherManager):
    取 PNG 全文件字节 → 每 4 字节各取最低位拼成 4 bit → 转十六进制字符
    → hex 串(长度 = filesize/4) → MD5 → 32 字符 ASCII 直接当 AES-256 key

用法:
    python keyderive.py                      # 打印 business / common 两把 key
    python keyderive.py --decrypt-server-config   # 顺带解密内置 server_config
"""
import base64
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, 'assets')
PAIRS = {'business': 'fast.png', 'common': 'api_yolobase_net.png'}


def lsb_md5_key(path):
    b = open(path, 'rb').read()
    n = len(b) - (len(b) % 4)          # 尾部 0-3 字节丢弃
    hexs = ''
    for i in range(0, n, 4):
        nib = (b[i] & 1) << 3 | (b[i + 1] & 1) << 2 | (b[i + 2] & 1) << 1 | (b[i + 3] & 1)
        hexs += format(nib, 'x')
    return hashlib.md5(hexs.encode()).hexdigest()


def aes_cbc_decrypt(key, iv, data):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    c = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    out = c.update(data) + c.finalize()
    pad = out[-1]
    return out[:-pad] if 0 < pad <= 16 else out


def decrypt_server_config(key):
    """assets/server_config = base64( AES-CBC(ServerResponse JSON, key, IV=?) )
    实测: 用 IV=0x00*16 解密时**只有第 1 个分组乱码**, 其余全对 —— 说明真实 IV 未知,
    而首块明文恰好是 16 字符的 '{"server_list": '。故: 剥 padding → 丢掉首块 → 补回前缀。
    末尾是 PKCS5 padding(0x10 * 16)。"""
    raw = open(os.path.join(ASSETS, 'server_config'), 'rb').read().strip()
    ct = base64.b64decode(raw)
    pt = aes_cbc_decrypt(key, b'\x00' * 16, ct)
    tail = pt[16:].decode('utf-8')
    doc = json.loads('{"server_list": ' + tail)
    if not isinstance(doc, dict):        # 兜底: 首块不是该前缀时当纯数组处理
        doc = {'server_list': json.loads(pt[min(i for i in (pt.find(b'[{'), pt.find(b'{"')) if i >= 0):]
                                          .decode('utf-8').rstrip('\x10\t\n '))}
    return doc


def main():
    keys = {}
    for kind, fname in PAIRS.items():
        p = os.path.join(ASSETS, fname)
        if not os.path.exists(p):
            print('缺少 %s, 先跑 python extract_assets.py <apk>' % p)
            return 1
        keys[kind] = lsb_md5_key(p)
        print('%-9s key=%s  (assets/%s, %d B)'
              % (kind, keys[kind], fname, os.path.getsize(p)))
    if '--decrypt-server-config' in sys.argv:
        doc = decrypt_server_config(keys['business'].encode())
        out = os.path.join(HERE, 'server_config_decrypted.json')
        json.dump(doc, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('\n内置兜底节点表 -> %s' % out)
        print(json.dumps(doc, ensure_ascii=False)[:400])
    return 0


if __name__ == '__main__':
    sys.exit(main())
