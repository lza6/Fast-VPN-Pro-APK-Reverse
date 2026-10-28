#!/usr/bin/env python3
"""精确基准: 顺序延迟 / 8并发 / 与拨号链路上限对比
用法: python bench.py [节点索引,...]   默认取前3个存活节点
"""
import json, os, socket, ssl, statistics, sys, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stress as S


def seq_latency(port, n=10):
    lat = []
    for _ in range(n):
        t0 = time.time()
        try:
            S.http_get_via_socks(port, 'www.cloudflare.com', 443, '/cdn-cgi/trace', use_tls=True)
            lat.append((time.time() - t0) * 1000)
        except Exception:
            pass
    return lat


def concur(port, workers=8, rounds=2):
    def one(_):
        t0 = time.time()
        try:
            b = S.http_get_via_socks(port, 'ip-api.com', 80, '/json/?fields=query')
            ok = b'"query"' in b
            return ok, (time.time() - t0) * 1000
        except Exception:
            return False, 0
    res = []
    for _ in range(rounds):
        with ThreadPoolExecutor(max_workers=workers) as ex:
            res += list(ex.map(one, range(workers)))
    return sum(1 for r in res if r[0]), len(res), [r[1] for r in res if r[0]]


def dialer_baseline():
    """经本机 xray(10808) 直接测 cloudflare 下行, 作为链路上限参考"""
    import urllib.request
    op = urllib.request.build_opener(
        urllib.request.ProxyHandler({'http': 'http://127.0.0.1:10808',
                                     'https': 'http://127.0.0.1:10808'}))
    for url in ('https://speed.cloudflare.com/__down?bytes=2000000',
                'http://speed.cloudflare.com/__down?bytes=2000000'):
        try:
            t0 = time.time()
            r = op.open(urllib.request.Request(url, headers={'User-Agent': 'curl/8'}), timeout=60)
            n = len(r.read())
            dt = time.time() - t0
            return round(n * 8 / dt / 1e6, 2)
        except Exception as e:
            print('  baseline attempt failed:', repr(e)[:80])
    return -1.0


def main():
    pm = json.load(open(os.path.join(HERE, 'portmap.json'), encoding='utf-8'))['portmap']
    st = json.load(open(os.path.join(HERE, 'stress_result.json'), encoding='utf-8'))
    alive_ports = [r['socks_port'] for r in st['results'] if r.get('ok')]
    picks = alive_ports[:3]
    out = {}
    print('dialer baseline (xray 10808 -> cloudflare 2MB): %.2f Mbps' % dialer_baseline())
    for p in picks:
        lat = seq_latency(p)
        okn, tot, clat = concur(p)
        info = next(r for r in st['results'] if r['socks_port'] == p)
        print(f"\n:{p} {info['server']} ({info.get('exit_country')})")
        if lat:
            print(f"  顺序延迟 n={len(lat)} P50={statistics.median(lat):.0f}ms "
                  f"min={min(lat):.0f} max={max(lat):.0f}")
        print(f"  8并发 x2轮: {okn}/{tot} 成功, P50={statistics.median(clat) if clat else 0:.0f}ms")
        out[p] = {'server': info['server'], 'seq_p50': round(statistics.median(lat)) if lat else None,
                  'concur': f'{okn}/{tot}'}
    json.dump(out, open(os.path.join(HERE, 'bench_result.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
