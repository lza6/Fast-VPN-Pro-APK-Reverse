#!/usr/bin/env python3
"""一键闭环: 收割 -> 合入内置兜底 -> 生成 mihomo 配置 -> 重启内核 -> 压测 -> 产出代理清单
用法:
  python pool_cycle.py                 # 全流程
  python pool_cycle.py --no-restart    # 不动 mihomo 进程, 只重生成配置+压测
  python pool_cycle.py --dialer 127.0.0.1:10808
"""
import argparse, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def run(mod_args):
    print('\n$', ' '.join(mod_args))
    r = subprocess.run([sys.executable] + mod_args, cwd=HERE)
    if r.returncode != 0:
        print('  !! 退出码', r.returncode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dialer', default=None)
    ap.add_argument('--base-port', type=int, default=24000)
    ap.add_argument('--no-restart', action='store_true')
    a = ap.parse_args()

    run(['harvest.py'])
    run(['merge_fallback.py'])
    build = ['build_mihomo.py', '--base-port', str(a.base_port)]
    if a.dialer:
        build += ['--dialer', a.dialer]
    run(build)

    if not a.no_restart:
        subprocess.run(['taskkill', '/F', '/IM', 'mihomo.exe'], capture_output=True)
        time.sleep(2)
        exe = os.path.join(HERE, 'mihomo.exe')
        if os.path.exists(exe):
            cf = open(os.path.join(HERE, 'mihomo.log'), 'a')
            subprocess.Popen([exe, '-f', 'mihomo_config.yaml', '-d', '.'],
                             cwd=HERE, stdout=cf, stderr=cf,
                             creationflags=0x00000008)  # DETACHED_PROCESS
            print('mihomo 已重启')
            time.sleep(5)
        else:
            print('!! mihomo.exe 不存在, 跳过重启')

    run(['stress.py'])

    st = json.load(open(os.path.join(HERE, 'stress_result.json'), encoding='utf-8'))
    alive = [r for r in st['results'] if r.get('ok')]
    out = os.path.join(HERE, 'proxies.txt')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('# fast-vpn-pro socks5 pool  %s  alive=%d/%d\n'
                % (time.strftime('%Y-%m-%d %H:%M:%S'), len(alive), st['total']))
        for r in alive:
            f.write('socks5://127.0.0.1:%d\n' % r['socks_port'])
    print('\n-> %s (%d 条)' % (out, len(alive)))


if __name__ == '__main__':
    main()
