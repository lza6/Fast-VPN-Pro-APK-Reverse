# PROTOCOL — 实现手册

给二次开发 / 对接方的最小实现说明。读完这一份可以直接写代码，不必翻报告。

---

## 1. 常量表

| 名称 | 值 | 来源 |
|------|-----|------|
| API base | `https://fastpro.fifavnet.net` | `assets/http_yolo_config.json` → `http_business.hostUrl`（`http_common.hostUrl` 同值） |
| 包名 | `com.fast.pro.smart.vpn` | `assets/appConfig` → `appPkgName` |
| 版本号 | `1.7.93` | 请求参数 `cv` |
| 节点列表 | `GET /cfg/newuser`、`GET /cfg/olduser` | `HttpUrlConstants` |
| 降级池 | `GET /cfg/lowuser` | 同上 |
| VIP 策略 | `GET /cfg/vip` | 同上 |
| 请求头 1 | `x-token` | `HEADER_X_TOKEN` |
| 请求头 2 | `X-Yolo-Auth`（= IV） | `HEADER_HTTP_AUTH` |
| 请求头 3 | `Authorization`（= HMAC-MD5） | `HEADER_COMMON_AUTH` |
| AES 变换 | `AES/CBC/PKCS5PADDING` | `RepositoryCipherManager` |
| business key | `MD5(hex(LSB(assets/fast.png)))` | 见 §2 |
| common key | `MD5(hex(LSB(assets/api_yolobase_net.png)))` | 见 §2 |
| business hmac key | `k3Rf65p9eaHJ3Rg` | `http_business.hmacMd5Key` |
| common x-token | 见 APK `http_common.headerXToken` | 已脱敏 |
| business x-token | `""`（空串） | `http_business.headerXToken` |

---

## 2. AES key 派生（必须实现，不要抄常量）

```python
n = len(pngbytes) - (len(pngbytes) % 4)        # 尾部 0-3 字节丢弃
hexs = ''
for i in range(0, n, 4):
    nib = (b[i]&1) << 3 | (b[i+1]&1) << 2 | (b[i+2]&1) << 1 | (b[i+3]&1)
    hexs += format(nib, 'x')
key = hashlib.md5(hexs.encode()).hexdigest().encode()   # 32 字节 ASCII = AES-256 key
```

- `fast.png`（14209 B）→ business key
- `api_yolobase_net.png`（455 B）→ common key
- **换一张图就换一次 key**，上游升级后必须重新派生，不要缓存跨版本。

用 `python keyderive.py` 直接打印两把 key。

---

## 3. 请求信封

### 3.1 GET（节点列表就这条）

```
GET {base}{path}?did={设备ID}&mcc={mcc}&mnc={mnc}&lang={lang}&cv=1.7.93&pkg=com.fast.pro.smart.vpn&os=Android
x-token: {business 或 common 的 headerXToken}
```

- `did` 只要是非空字符串即可，服务端不做严格校验。
- `mcc` 建议填 `310`（美国）。填 `460/461/432/467`（大陆/香港/澳门/台湾）会命中
  `limit_region` 标签，客户端侧会额外做本地地区限制，但**服务端仍下发同样节点**。
- GET **不需要** `X-Yolo-Auth` / `Authorization`，也不加密请求体。

### 3.2 POST（上报类，与节点无关）

```
POST {base}{path}
x-token: ...
X-Yolo-Auth: {16 位随机字母数字}
Authorization: HmacMD5.base64(base64_ciphertext, hmac_key)
body: base64(AES-256-CBC(json, key, IV=上面那个 16 位随机串))
```

注意 HMAC 的输入是**base64 之后的密文**，不是原始 json。

---

## 4. 响应解析（双形态，必须先判头）

```
if resp.headers['X-Yolo-Auth'] 存在且非空:
    plain = AES-256-CBC-decrypt( key, IV=该头, base64_decode(body) )
else:
    plain = body            # 明文 JSON（错误 / 降级路径）
```

`Content-Type` 恒为 `text/plain; charset=utf-8`，别用它判断是否加密。

---

## 5. 节点对象字段

```json
{
  "name": "New York - 217",
  "server": "<NODE_IP>",
  "server_port": 10000,
  "background_port": 10000,
  "password": "<SS_PASSWORD>",
  "method": "aes-256-gcm",
  "mode": "tcp_and_udp",
  "weight": 85,
  "gip": "US",
  "is_auto": true,
  "is_vip": false,
  "isp": "do",
  "city": "New York",
  "iso_code": "US",
  "app_conn_limit": 1000000,
  "mb_ip": "",
  "ss_type": "vps",
  "ss_asn": ""
}
```

| 字段 | 说明 |
|------|------|
| `server` / `server_port` | SS 服务端地址 |
| `password` / `method` | SS 加密口令与算法（实测全部 `aes-256-gcm`） |
| `background_port` | 与 `server_port` 同值 |
| `weight` | 客户端排序权重，越大越优先 |
| `is_vip` | 是否 VIP 专属（`false` 才是免费可用） |
| `ss_type` | `vps` = 运营方自租 VPS（**合规关键字段**） |
| `app_conn_limit` | 单节点连接上限声明值 |

分组结构：`data.server_list[] = {group_id, iso_code, desc, normal_show_cnt, vip_show_cnt, servers[]}`。

---

## 6. 最小实现骨架

```python
import base64, hashlib, json, ssl, urllib.request
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

HOST = 'https://fastpro.fifavnet.net'

def lsb_md5_key(path):
    b = open(path, 'rb').read(); n = len(b) - len(b) % 4; h = ''
    for i in range(0, n, 4):
        h += format((b[i]&1)<<3 | (b[i+1]&1)<<2 | (b[i+2]&1)<<1 | (b[i+3]&1), 'x')
    return hashlib.md5(h.encode()).hexdigest().encode()

KEY = lsb_md5_key('assets/fast.png')

def get_nodes(did='deadbeefdeadbeef', path='/cfg/newuser'):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                     urllib.request.HTTPSHandler(context=ctx))   # 绕开环境代理
    q = f'{HOST}{path}?did={did}&mcc=310&mnc=260&lang=en&cv=1.7.93&pkg=com.fast.pro.smart.vpn&os=Android'
    r = op.open(urllib.request.Request(q, headers={'x-token': '', 'User-Agent': 'okhttp/4.9.3'}))
    iv = r.headers.get('X-Yolo-Auth')
    body = r.read()
    if not iv:
        return json.loads(body)
    d = Cipher(algorithms.AES(KEY), modes.CBC(iv.encode())).decryptor()
    pt = d.update(base64.b64decode(body)) + d.finalize()
    return json.loads(pt[:-pt[-1]])
```

---

## 7. 必避坑

1. **不要照抄 AES key 常量** —— 由 PNG 派生的，换版本就失效。
2. **首块乱码陷阱**（内置 `server_config`）：IV 未知时 CBC 只有第 1 块错，
   直接丢前 16 字节会连 `{"server_list": ` 前缀一起丢掉，得补回来。
3. **`Content-Type` 不可用于判加密**，只能看 `X-Yolo-Auth` 头。
4. **`hmacMd5Key` 只对 business 有效**，common 侧该字段为空 → 不签名。
5. **参数扫描无法扩容**：`mcc`/`cv`/`lang`/`path` 24 组组合拿到的唯一节点集合完全一致。
6. **节点集合不轮换**：同一 `did` 连拉 30 轮一模一样；换 `did` 也不变。池子上限即下发数量。
7. **本机测节点前先排除本地网络**：若直连节点端口超时，先用第三方（如 `check-host.net`
   `check-tcp` API）做海外多探针交叉验证，否则会把「本地网络不通」误判成「节点全死」。
8. **测吞吐/延迟必须绕开环境代理**：`ProxyHandler({})` + 裸 socket，否则数据全是代理的。
