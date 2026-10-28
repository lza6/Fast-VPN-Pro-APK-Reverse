#!/usr/bin/env python3
"""采样轮换率: 反复请求 /cfg/newuser, 统计 unique IP 增长曲线"""
import json, random, sys, time
import harvest as H

def main(rounds=30):
    did = ''.join(random.choice('0123456789abcdef') for _ in range(16))
    seen = {}
    curve = []
    for i in range(rounds):
        params = {'did': did, 'mcc': '310', 'mnc': '260', 'lang': 'en',
                  'cv': H.CV, 'pkg': H.PKG, 'os': 'Android'}
        r = H.fetch('/cfg/newuser', params)
        if not r['ok']:
            print('fail', r.get('why')); continue
        sl = (r['json'].get('data') or {}).get('server_list') or []
        ids = []
        for g in sl:
            for s in g.get('servers') or []:
                k = (s['server'], s['server_port'], s['password'])
                seen[k] = s
                ids.append(s['server'])
        curve.append({'round': i + 1, 'got': len(ids), 'uniq_total': len({k[0] for k in seen})})
        print(f"round {i+1:3d}: got={len(ids):3d} uniq_ips_total={len({k[0] for k in seen}):4d}")
        time.sleep(0.4)
    json.dump({'curve': curve, 'uniq': len(seen),
               'nodes': [dict(v, _k=list(k)) for k, v in seen.items()]},
              open(r'D:\apk-analysis\fastvpn\rotation_sample.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('TOTAL unique (ip,port,pw):', len(seen), ' unique ips:', len({k[0] for k in seen}))

if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
