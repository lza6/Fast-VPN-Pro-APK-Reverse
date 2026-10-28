#!/usr/bin/env python3
"""从任意 Fast VPN Pro APK 中提取逆向所需的 4 个 assets。
用法: python extract_assets.py <apk路径>
产出: ./assets/{fast.png, api_yolobase_net.png, http_yolo_config.json, server_config}
说明: 不依赖 apktool, 纯 zipfile —— 这 4 个文件都是未编译的 assets, 直接可读。
"""
import os
import sys
import zipfile

WANT = ['assets/fast.png', 'assets/api_yolobase_net.png',
        'assets/http_yolo_config.json', 'assets/server_config']
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    apk = sys.argv[1]
    if not os.path.exists(apk):
        print('APK 不存在:', apk)
        return 1
    os.makedirs(OUT, exist_ok=True)
    with zipfile.ZipFile(apk) as z:
        names = set(z.namelist())
        for w in WANT:
            if w not in names:
                print('  缺失:', w)
                continue
            dst = os.path.join(OUT, os.path.basename(w))
            with z.open(w) as src, open(dst, 'wb') as f:
                f.write(src.read())
            print('  %-32s -> %s (%d B)' % (w, dst, os.path.getsize(dst)))
    print('\n完成。下一步: python keyderive.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())
