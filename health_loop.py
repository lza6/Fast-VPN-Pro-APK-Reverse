#!/usr/bin/env python3
"""Fast VPN Pro 节点池常驻健康检查

为什么必须自己跑：new-api 的 TraceProbes() 里 `if e.source != "free" { continue }`
—— 住宅源(source=residential)的条目**不会被 new-api 做真实出口拨测**。
所以 proxies.txt 的正确性只能由本脚本保证。

行为：
  1. 对每个 socks listener 做真实探测（SS 握手 → 出口 IP → HTTPS）
  2. 出口 IP 必须等于节点 IP，否则判异常（防止上游把节点偷偷改成中转）
  3. **双阈值摘除**：连续 2 轮失败才移出 proxies.txt（单轮抖动很常见）
  4. 原子重写 proxies.txt（new-api 侧再触发一次重载即可生效）

用法：
  python health_loop.py --once                 # 跑一轮后退出（cron 用）
  python health_loop.py --interval 600         # 常驻，每 10 分钟一轮
  python health_loop.py --once --dialer-check  # 额外打印当前拨号路径提示
"""
import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stress as S  # 复用裸 SOCKS5 探测实现

STATE = os.path.join(HERE, 'health_state.json')
PROXIES = os.path.join(HERE, 'proxies.txt')
NODES = os.path.join(HERE, 'nodes.json')
PORTMAP = os.path.join(HERE, 'portmap.json')
STRIKE_LIMIT = 2          # 连续失败几轮才摘除


def load_json(p, default):
    if not os.path.exists(p):
        return default
    return json.load(open(p, encoding='utf-8'))


def probe(pm):
    """返回 (ok, detail)。ok 的判据不只是能连上，还要出口 IP == 节点 IP。"""
    try:
        raw = S.http_get_via_socks(pm['socks_port'], 'ip-api.com', 80,
                                   '/json/?fields=status,query,country,isp')
        body = raw.split(b'\r\n\r\n', 1)[-1].decode('utf-8', 'replace')
        j = json.loads(body)
        exit_ip = j.get('query')
        if j.get('status') != 'success':
            return False, 'api status=%r' % j.get('status')
        if exit_ip != pm['server']:
            # 出口 IP 与节点不一致 = 上游改成了中转，或不认识的中间层
            return False, 'exit_mismatch exit=%s node=%s' % (exit_ip, pm['server'])
        return True, exit_ip
    except Exception as e:
        return False, repr(e)[:120]


def one_round(portmap, state, strike_limit=STRIKE_LIMIT):
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=min(25, len(portmap))) as ex:
        results = list(ex.map(probe, portmap))
    alive, dead, mismatched = [], [], []
    for pm, (ok, detail) in zip(portmap, results):
        key = pm['server']
        rec = state.setdefault(key, {'strikes': 0, 'ok_streak': 0})
        if ok:
            rec['strikes'] = 0
            rec['ok_streak'] = rec.get('ok_streak', 0) + 1
            rec['last_ok'] = time.strftime('%Y-%m-%dT%H:%M:%S')
            alive.append(pm)
            continue
        rec['strikes'] = rec.get('strikes', 0) + 1
        rec['ok_streak'] = 0
        rec['last_err'] = detail
        if 'exit_mismatch' in detail:
            mismatched.append((pm['server'], detail))
        # 抖动容忍：只有"曾经通过过"且未超阈值的节点才继续留在池里。
        # 从未通过过的新节点不入池 —— 否则首轮会把死节点也写进去。
        if rec.get('last_ok') and rec['strikes'] < strike_limit:
            alive.append(pm)
        else:
            dead.append((pm['server'], detail, rec['strikes']))
    return alive, dead, mismatched, round(time.time() - t0, 1)


def write_proxies(alive):
    tmp = PROXIES + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('# fast-vpn-pro socks5 pool  %s  alive=%d\n'
                % (time.strftime('%Y-%m-%d %H:%M:%S'), len(alive)))
        for pm in sorted(alive, key=lambda x: x['socks_port']):
            f.write('socks5://127.0.0.1:%d\n' % pm['socks_port'])
    os.replace(tmp, PROXIES)          # 原子替换，new-api 不会读到半个文件


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--interval', type=int, default=600)
    ap.add_argument('--strike-limit', type=int, default=STRIKE_LIMIT)
    a = ap.parse_args()

    portmap = load_json(PORTMAP, {}).get('portmap', [])
    if not portmap:
        print('缺少 portmap.json —— 先跑 python build_mihomo.py')
        return 1
    nodes = {n['server']: n for n in load_json(NODES, {}).get('node_list', [])}
    state = load_json(STATE, {})

    while True:
        alive, dead, mismatched, elapsed = one_round(portmap, state, a.strike_limit)
        write_proxies(alive)
        json.dump(state, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

        print('[%s] 探 %d / 在用 %d / 本轮摘除 %d / %.1fs'
              % (time.strftime('%H:%M:%S'), len(portmap), len(alive), len(dead), elapsed))
        for ip, detail, n in dead:
            nm = nodes.get(ip, {})
            print('  - 摘除 %-16s %s/%s  %s  连续%d轮'
                  % (ip, nm.get('iso_code', '??'), nm.get('city', ''), detail, n))
        for ip, detail in mismatched:
            print('  ! 出口不符 %s  %s' % (ip, detail))
        print('  -> %s' % PROXIES)

        if a.once:
            return 0
        time.sleep(max(60, a.interval))


if __name__ == '__main__':
    sys.exit(main())
