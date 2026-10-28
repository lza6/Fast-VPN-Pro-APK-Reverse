# Fast VPN Pro 1.7.93 逆向报告

> 样本：`Fast_VPN_Pro_-_Secure_Service_1.7.93_modded_by_PlatinumMods.apk`（34,389,415 B，`com.fast.pro.smart.vpn`）
> 分析时间：2026-10-29 ｜ 工作区：`D:\apk-analysis\fastvpn`
> 结论先行：**零鉴权云端接口直出 Shadowsocks 节点，20/20 实测可用，出口 IP = 节点 IP（直出，无中转）**

---

## 1. 架构定性

| 维度 | 结论 | 依据 |
|------|------|------|
| VPN 内核 | **shadowsocks-android**（`com.github.shadowsocks`） | 原生库 `libsslocal.so`(19.2 MB) / `libtun2socks.so` / `libredsocks.so`；dex 内含 `com/github/shadowsocks/bg/VpnService`、`database/Profile` |
| 节点协议 | Shadowsocks AEAD **aes-256-gcm**，`tcp_and_udp` | 云端下发字段 `method` / `mode` |
| 业务框架 | 自研 `com.yolo.*`（networklibrary / base / iap / cache / referrerlibrary） | 包结构 + `StringFog` 字符串混淆 |
| 网络层 | OkHttp；**无拦截器加密**，加密在 `RequestManager` 手工完成 | `RequestManager.java` |
| 配置来源 | **自有 HTTP API**（非 Firebase RTDB、非 RemoteConfig） | `assets/http_yolo_config.json` 明写 `hostUrl` |
| 商业壳体 | 广告 SDK：AdMob / Kidoz / Prado / Yoadx；归因 AppsFlyer / Adjust | 广告单元 ID、`yolo_referrer.properties` |

节点是 **Shadowsocks** 这一点很关键：拿到 `server/port/password/method` 就能直接起本地 SOCKS5，
不需要 OpenVPN 证书握手、也不需要 Hysteria2 的 UDP 隧道 —— 池化成本最低的一类。

---

## 2. 配置与密钥全链

### 2.1 明文配置（`assets/http_yolo_config.json`）

```json
{
  "http_business": {
    "assetsResXTokenName": "fast.png",
    "headerXToken": "",
    "hmacMd5Key": "k3Rf65p9eaHJ3Rg",
    "hostUrl": "https://fastpro.fifavnet.net"
  },
  "http_common": {
    "assetsResXTokenName": "api_yolobase_net.png",
    "headerXToken": "<COMMON_X_TOKEN>",
    "hmacMd5Key": "",
    "hostUrl": "https://fastpro.fifavnet.net"
  }
}
```

`business` 与 `common` 指向同一域名，区别只在用途与密钥。

### 2.2 AES 密钥藏在 PNG 的最低位

`RepositoryCipherManager.createCipherKey()` + `AssetsEncryptUtils.generateAssetsStr()`：

```
取 PNG 全文件字节 → 每 4 字节取各自最低位拼成 4 bit → 转十六进制字符
→ 长度 = filesize/4 的十六进制串 → MD5(该串) → 32 字符 ASCII 直接当 AES-256 key
```

实测推导结果（可复现）：

| 载体 | 字节数 | 派生 AES-256 key |
|------|--------|------------------|
| `assets/fast.png`（business） | 14209 | `58a1eaabcb0b9cb840925e97c8da7f41` |
| `assets/api_yolobase_net.png`（common） | 455 | `58e6717e398cf10407ced4e142f69bf3` |

**注意**：key 不是写死的常量，改一次 PNG 就换一次 key；必须走 LSB 派生，不要试图 strings 搜。

### 2.3 请求/响应信封

```
POST {host}/{path}
  x-token: <headerXToken>                                  # business 为空串
  X-Yolo-Auth: <IV>                                        # 16 位随机字母数字
  Authorization: HmacMD5( base64(ciphertext), hmacMd5Key ) # 仅 business
  body = base64( AES-256-CBC/PKCS5( json, key, IV ) )

响应
  X-Yolo-Auth: <IV>                                        # 服务端回传同一 IV
  body = base64( AES-256-CBC/PKCS5( json, key, IV ) )
  若响应无 X-Yolo-Auth 头 → 明文 JSON（错误/降级路径，先判空头再解）
```

`HmacMD5` 的输入是 **base64 后的密文**（不是原始 json），business 用 `k3Rf65p9eaHJ3Rg`，
common 侧 `hmacMd5Key` 为空 → 不校验。

### 2.4 字符串混淆（`StringFog`）

全部常量走 `StringFog.decrypt(base64(data), base64(key))` = 逐字节 XOR 循环密钥（megatronking/stringfog）。
本次已批量还原 1122 条，产物见 `stringfog_targets.txt`。关键项：

| 常量 | 还原值 |
|------|--------|
| `HEADER_COMMON_AUTH` | `Authorization` |
| `HEADER_HTTP_AUTH` | `X-Yolo-Auth` |
| `HEADER_X_TOKEN` | `x-token` |
| `Cipher.getInstance` | `AES/CBC/PKCS5PADDING` |

---

## 3. 接口清单（`https://fastpro.fifavnet.net`）

| 路径 | 方法 | 用途 | 实测 |
|------|------|------|------|
| `/cfg/newuser` | GET | **节点列表（主力）** | 200，20 节点 |
| `/cfg/olduser` | GET | 节点列表（老用户） | 200，同 20 节点 |
| `/cfg/lowuser` | GET | 低活用户降级池 | 200，5 节点（挪威，全死） |
| `/cfg/vip` | GET | VIP 时长策略（`rv_once_duration` / `rv_max_duration`） | 200 |
| `/cfg/ad` | GET | 广告配置 | 400（参数不完整） |
| `/want`、`/usage/user`、`/connect/user`、`/prod/hi` | POST | 上报/心跳 | 405（GET 不允） |
| `/prod/app/business/config` | - | 常量已定义但**未被调用**（死代码） | - |
| `/report`、`/vip/status`、`/prod/api/first_open/`、`/install_call`、`/goddo/block_white_list`、`/login/visitor`、`/prod/api/subscription/cfg`、`/pay/gp` | - | 上报/内购/风控 | 与节点无关 |

GET 请求的查询参数由 `RequestManager` 自动附加：
`did`(设备 ID)、`mcc`、`mnc`、`lang`、`cv`(版本号)、`pkg`、`os`、utm 系列。

### 3.1 节点来源判定（`UserLimitHandler.getCfgUrlByAdLimit()`）

```
VIP 状态        → /cfg/newuser
需要看广告      → /cfg/newuser
其他            → /cfg/olduser
```

响应模型 `ServerResponse`：`server_list[] → ServerGroup{group_id, iso_code, desc, servers: Profile[]}`，
`Profile` 即 shadowsocks 的节点对象。

### 3.2 零鉴权确认

`x-token` 传空串、**不带任何签名**，`/cfg/newuser` 仍返回 200 全量节点。
服务端只校验 `pkg` 形态与版本号，不做设备指纹/签名/安装来源校验。

---

## 4. 节点池实况

### 4.1 规模

| 项 | 值 |
|----|----|
| 云端下发（`newuser`/`olduser`） | **20 个**，全部美国 DigitalOcean |
| 云端下发（`lowuser`） | **5 个**，挪威 OneProvider，**全死** |
| APK 内置兜底（`assets/server_config`） | **1 个**，Ashburn gthost，**已死** |
| 唯一出口 IP | 25（无同 IP 多端口） |
| 参数扫描扩容 | ❌ `mcc`×`cv`×`lang`×`path` 共 24 组组合，唯一节点数恒为 25 |
| 轮换 | ❌ 同一 `did` 连拉 30 轮，节点集合完全一致 |

**即池子上限就是 25 个，其中 20 个可用。**

### 4.2 节点字段

```json
{
  "name": "New York - 217", "server": "198.51.100.10", "server_port": 10000,
  "background_port": 10000, "password": "<SS_PASSWORD>",
  "method": "aes-256-gcm", "mode": "tcp_and_udp", "weight": 85,
  "gip": "US", "is_auto": true, "is_vip": false, "isp": "do",
  "city": "New York", "iso_code": "US",
  "app_conn_limit": 1000000, "ss_type": "vps"
}
```

- 20 个美国节点**共用一个密码** `<SS_PASSWORD>`，端口统一 `10000`；
  5 个挪威节点同样共用一个密码 `<SS_PASSWORD>`，端口统一 `8881`。
  即整池只有 **两套凭证**，任一被吊销/轮换即对应区域整片失效。
- `weight: 85`、`app_conn_limit: 1000000`（单节点连接上限声明值，无实测反证）。
- `ss_type: "vps"` ⇒ 运营商自租 VPS（见第 7 节合规）。

### 4.3 内置兜底节点的加密格式

`assets/server_config`（792 B base64 → 592 B = 37 个 AES 分组）：

```
base64_decode → AES-256-CBC(ServerResponse JSON, key=MD5(fast.png LSB), IV=?)
payload = {"server_list":[{"group_id":"us", ..., "servers":[{Ashburn-3413,
           203.0.113.15:8090, password=<SS_PASSWORD>, gthost}]}],
           "disconnect_time":86400, "special_mcc":["460","461","432","467"],
           "special_region":["CN"], "special_language":["zh"], "speical_lang":[]}
```

**解密细节（踩过的坑）**：真实 IV 未在静态代码中恢复，但用 `IV=0x00*16` 解密时
**只有第 1 个分组乱码、其余 36 个分组全部正确**（CBC 特性：IV 只影响首块）。
而首块明文恰好是 16 字符的 `{"server_list": `，因此可用「剥 padding → 丢弃首块 → 补回该前缀」
还原完整 JSON。直接搜 `[{` 定位会丢掉 `disconnect_time` 等尾部字段。

`special_region: ["CN"]` 说明该 App 对中国大陆用户有专门的分支策略（本次实测未触发额外节点）。

---

## 5. 测活结果（真实协议握手，非 TCP 连通）

**测活方法**：`mihomo` 每节点一个 SS outbound + 本地 socks listener → 裸 SOCKS5 握手 →
`ip-api.com` 取真实出口 IP → `www.cloudflare.com/cdn-cgi/trace` 验 HTTPS 通路 → `speed.cloudflare.com` 测下行。

| 指标 | 结果 |
|------|------|
| 字节级存活（SS 握手 + 出口 IP 校验） | **20 / 26**（US 20/20，NO 0/5，内置兜底 0/1） |
| 出口 IP = 节点 IP | **20 / 20**（直出，不经中转） |
| 出口 ISP | DigitalOcean, LLC |
| 顺序延迟 P50（经双跳链路） | ~1220 ms（3 节点各 10 次） |
| 下行吞吐 P50 | **3.5 Mbps**（min 1.38 / max 3.67） |
| 8 并发 × 2 轮 | **16/16 成功**（3 个抽样节点全部满成功率） |

**测量偏差声明**：本机直连 DigitalOcean 网段（162.243/107.170/192.241/104.131）全部超时
（`1.1.1.1:443` 也不通，属本机出口网络限制），故测活经本机已有的 xray 隧道二次拨号完成。
同一时刻 `check-host.net` 8 个海外探针均能连通这些节点（8/8 OK），可证**节点本身健康**，
但上表延迟/带宽是**双跳叠加后的保守值**，真实直连 RTT 与带宽应优于该数字。

**第三方交叉验证（check-host.net）**：

| 目标 | 结果 |
|------|------|
| `198.51.100.10:10000` | 8/8 探针 OK（at/hu/il/ir/pt/ru/sg/tr） |
| `198.51.100.11:10000` | 7/8 OK |
| `203.0.113.10:8881`（NO） | **0/8，全部 Connection refused** |
| `203.0.113.15:8090`（内置兜底） | 1/6，其余 refused/timeout → 判死 |

---

## 6. 协议转换层（池化）

```
节点(SS aes-256-gcm)
  └─ mihomo  single process，N 个 listener
        listener n000 → socks 127.0.0.1:24000 → proxy n000
        listener n001 → socks 127.0.0.1:24001 → proxy n001
        ...
  └─ new-api：TRYINGOPEN_PROXY_FILE 指向 proxies.txt 即可（每行 socks5://host:port）
```

选 mihomo 而非自写 SS 客户端的理由：一份 YAML 映射 25 个端口、单进程、无外部依赖，
`listeners[].proxy` 把端口与节点硬绑定，不存在规则误路由。

---

## 7. 合规判定（必须披露）

| 事实 | 判定 |
|------|------|
| `ss_type = "vps"` | 节点是**上游运营商自租的 VPS**（DigitalOcean 纽约 20 台 + OneProvider 挪威 5 台） |
| 20 台共用同一密码、统一端口 10000 | 属于运营方内部节点池，不是公开志愿源 |
| 接口零鉴权 | **接口设计缺陷**，不等于授权第三方批量取用 |

按本项目既定红线：**凭证获取 ≠ 使用权**。这批节点不属于 VPNGate 那类公开志愿源，
把上游付费基础设施批量挂进生产代理池属于盗用基础设施，风险由运营方承担。
本报告的定位是**协议安全性研究 + 池化可行性验证**；是否投产由使用者自行决策。

---

## 8. 产物清单

| 文件 | 说明 |
|------|------|
| `probe.py` | 最小协议探针（30 行可抄） |
| `harvest.py` | 云端全量收割（多 path × 多 mcc） |
| `rotation_test.py` | 轮换率采样 |
| `merge_fallback.py` | 内置兜底节点解密合入 |
| `build_mihomo.py` | 生成 25 端口 mihomo 配置（支持 `--dialer`） |
| `stress.py` | 裸 SOCKS5 压测（出口 IP / 延迟 / 吞吐） |
| `bench.py` | 顺序延迟 + 8 并发 + 链路上限对比 |
| `pool_cycle.py` | 一键闭环：收割→配置→重启→压测→`proxies.txt` |
| `demo_server.py` / `demo.html` | 面板 8955（节点/统计/实时探测/重新拉取/代理清单） |
| `nodes.json` | 26 节点全量（含 `ss_type`、`weight` 等原始字段） |
| `stress_result.json` / `bench_result.json` | 实测原始数据 |
| `proxies.txt` | new-api 可直接吃的 20 条 socks5 |
| `stringfog_targets.txt` | 1122 条混淆常量还原结果 |
| `server_config_decrypted.json` | 内置兜底节点明文 |
