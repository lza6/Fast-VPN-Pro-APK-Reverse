# Fast VPN Pro 1.7.93 — 协议逆向与节点池

> Android VPN 客户端逆向（`com.fast.pro.smart.vpn`，Shadowsocks 内核）。
> **零鉴权**云端接口直出节点，20/20 实测量可用（SS 握手通过、出口 IP = 节点 IP、HTTPS 通、8 并发满成功率）。
> 本仓库为**协议安全研究**：完整逆向报告 + 可复现工具链 + 脱敏样例。**不含任何真实凭证**。

## 一图看懂

```
APK assets/fast.png ──LSB→hex→MD5──▶ AES-256 key
                                          │
GET /cfg/newuser (零鉴权) ──▶ base64(AES-CBC(json)) ──解密──▶ server_list[]
                                          │
                              Shadowsocks aes-256-gcm 节点
                                          │
                              mihomo 每节点一个 socks5 端口
                                          │
                              new-api  TRYINGOPEN_PROXY_FILE 直吃
```

## 协议三句话

1. `GET https://fastpro.fifavnet.net/cfg/newuser?did=..&mcc=310&mnc=260&lang=en&cv=1.7.93&pkg=com.fast.pro.smart.vpn&os=Android`，`x-token` 传空串也返回 200。
2. 响应头 `X-Yolo-Auth` 是 IV，`body = base64(AES-256-CBC/PKCS5(json))`；无该头则是明文 JSON。
3. AES key = `MD5( hex(assets/fast.png 每 4 字节最低位拼成的二进制) )`，32 字符 ASCII 当 AES-256 key。**不是常量，必须派生。**

细节见 [`docs/PROTOCOL.md`](docs/PROTOCOL.md)（实现手册，可直接照抄）。

## 快速开始

```bash
pip install cryptography

# 1) 从你自己的 APK 里提取 4 个 assets（纯 zipfile，不需要 apktool）
python extract_assets.py /path/to/Fast_VPN_Pro_1.7.93.apk

# 2) 派生 AES key（并可选解密内置兜底节点表）
python keyderive.py --decrypt-server-config

# 3) 最小探针：打一次接口看明文
python probe.py

# 4) 全量收割 -> nodes.json
python harvest.py

# 5) 一站式：收割 -> mihomo 配置 -> 压测 -> proxies.txt
#    需要 mihomo 二进制放在仓库根目录
python pool_cycle.py

# 6) 面板
python demo_server.py      # http://127.0.0.1:8955/
```

> 若宿主机直连节点网段不通，可用 `python pool_cycle.py --dialer 127.0.0.1:10808`
> 经本机已有隧道二次拨号（**只影响拨号路径**）。能直连就不要加，多一跳纯增延迟。
> 判断"节点死"之前，务必先用第三方多探针（如 check-host.net）排除本地网络问题。

## 实测数据（2026-10-29）

| 指标 | 值 |
|------|-----|
| 云端节点数 | 25（20 美国 + 5 挪威） |
| 协议层存活 | **20 / 26**（美国 20/20，挪威 0/5，内置兜底 0/1） |
| 出口 IP = 节点 IP | 20 / 20（直出无中转） |
| 出口 ISP | DigitalOcean, LLC |
| 下行吞吐 P50 | 3.5 Mbps（min 1.38 / max 3.67） |
| 8 并发 × 2 轮 | 16/16 成功（3 个抽样节点全满） |
| 参数扫描扩容 | ❌ `mcc`×`cv`×`lang`×`path` 24 组组合，唯一节点恒为 25 |
| 节点轮换 | ❌ 同一 `did` 连拉 30 轮集合完全一致 |

> 上表延迟/带宽经二次拨号测得（测试机出口对 DigitalOcean 网段全端口超时，`1.1.1.1:443` 亦不通），
> 属**保守值**。同期 `check-host.net` 8 个海外探针 8/8 连通这些节点，可证节点自身健康。

## 文件

| 文件 | 用途 |
|------|------|
| `extract_assets.py` | 从 APK 提取 `fast.png` / `api_yolobase_net.png` / `http_yolo_config.json` / `server_config` |
| `keyderive.py` | PNG LSB → AES-256 key；解密内置 `server_config` 兜底节点表 |
| `probe.py` | 最小协议探针（30 行可抄） |
| `harvest.py` | 云端收割（多 path × 多 mcc） |
| `rotation_test.py` | 节点集合轮换率采样 |
| `merge_fallback.py` | 把内置兜底节点合入 `nodes.json` |
| `build_mihomo.py` | 生成 N 端口 mihomo 配置（每节点一个 socks listener） |
| `stress.py` | 裸 SOCKS5 压测（真实出口 IP / 延迟 / 吞吐） |
| `health_loop.py` | **常驻健康检查**：出口 IP 校验 + 双阈值摘除 + 原子重写 `proxies.txt` |
| `bench.py` | 顺序延迟 + 8 并发 + 链路带宽上限对照 |
| `pool_cycle.py` | 一键闭环（收割 → 配置 → 重启 → 压测 → 清单） |
| `demo_server.py` + `demo.html` | 池子面板 `:8955`（节点 / 统计 / 实时探测 / 重新拉取 / 代理清单） |
| `docs/PROTOCOL.md` | **实现手册**：常量表 / key 派生 / 信封 / 字段表 / 最小骨架 / 必避坑 |
| `docs/REVERSE_REPORT.md` | 完整逆向报告（架构 / 密钥链 / 接口清单 / 测活 / 合规） |
| `docs/NEWAPI_INTEGRATION.md` | new-api `TRYINGOPEN_PROXY_FILE` 接入 + 容器网络坑 |
| `data/nodes.sample.json` | 脱敏节点样例（真实数据请自己跑 `harvest.py`） |

## 关键发现

- **Node protocol**：整个池子统一 `aes-256-gcm` / `tcp_and_udp` —— 是所有 VPN 类型里池化成本最低的一类，不需要 OpenVPN 证书握手或 Hysteria2 UDP 隧道。
- **AES key 藏在 PNG 最低位**：`MD5(hex(LSB of every 4 bytes))`，换图即换 key，`strings` 搜不到。
- **框架可横向复用**：`com.yolo.networklibrary` 是白标 VPN 工厂的通用框架，换 App 只需换 `hostUrl` + 重新派生 key。
- **常量混淆**：`StringFog`（megatronking/stringfog）逐字节 XOR，已批量还原 1122 条。
- **内置兜底节点**：`assets/server_config` 用同一把 key 加密，IV 未知（CBC 只影响首块），可还原。

## 合规声明

节点字段 `ss_type = "vps"` ⇒ 这批节点是**上游 VPN 运营商自租的 VPS**（DigitalOcean 纽约 20 台 + OneProvider 挪威 5 台），
不是 VPNGate 那类公开志愿源；20 台还共用同一密码。云端接口无鉴权属**上游设计缺陷**，
不等于授权第三方批量取用。

本仓库仅用于**协议安全研究**。把上游付费基础设施接入生产代理池属于盗用，
请勿照做；由此产生的风险与责任由使用者自行承担。仓库内所有真实节点 IP / 口令 / token 均已替换为占位符。

## 免责

仅供安全研究与教育用途。使用者需自行确认所在地法律法规与上游服务条款。
