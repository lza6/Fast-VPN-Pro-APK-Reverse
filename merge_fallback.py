#!/usr/bin/env python3
"""把内置兜底节点表（assets/server_config 解出的 server_config_decrypted.json）
合入 nodes.json，并顺手探测其余 cfg 端点。
前置: python keyderive.py --decrypt-server-config
"""
import json
import os

import harvest as H

HERE = os.path.dirname(os.path.abspath(__file__))
NODES = os.path.join(HERE, 'nodes.json')
FALLBACK = os.path.join(HERE, 'server_config_decrypted.json')


def load_fallback():
    if not os.path.exists(FALLBACK):
        print('缺少 server_config_decrypted.json，先跑 python keyderive.py --decrypt-server-config')
        return []
    doc = json.load(open(FALLBACK, encoding='utf-8'))
    out = []
    for g in doc.get('server_list') or []:
        for s in g.get('servers') or []:
            out.append(dict(s, group_id=g.get('group_id'), group_desc=g.get('desc'),
                            iso_code=g.get('iso_code')))
    return out


def main():
    d = json.load(open(NODES, encoding='utf-8'))
    have = {(n['server'], n['server_port']) for n in d['node_list']}
    added = 0
    for e in load_fallback():
        if (e['server'], e['server_port']) not in have:
            d['node_list'].append(e)
            added += 1
    d['nodes'] = len(d['node_list'])
    d['unique_ips'] = len({n['server'] for n in d['node_list']})
    json.dump(d, open(NODES, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('merged fallback: +%d -> total %d nodes / %d ips'
          % (added, d['nodes'], d['unique_ips']))

    for path in ['/cfg/ad', '/want', '/usage/user', '/connect/user', '/cfg/lowuser']:
        params = {'did': 'abcd1234abcd1234', 'mcc': '310', 'mnc': '260', 'lang': 'en',
                  'cv': H.CV, 'pkg': H.PKG, 'os': 'Android'}
        r = H.fetch(path, params)
        if r['ok']:
            body = json.dumps(r['json'], ensure_ascii=False)
            print('%s: OK len=%d %s' % (path, len(body), body[:200]))
        else:
            print('%s: FAIL %s' % (path, r.get('why')))


if __name__ == '__main__':
    main()
