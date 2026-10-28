# new-api 对接交接文档

> 给「对接会话」的执行手册。**照着做即可，不需要重新逆向。**
> 上游来源：Fast VPN Pro 1.7.93 → 20 个美国 Shadowsocks 节点（aes-256-gcm）
> 交接物：`proxies.txt`（每行 `socks5://127.0.0.1:2400X`）+ `mihomo` 转换层
> 本机工作区：`D:\apk-analysis\fastvpn`

---

## 0. 边界声明（先读，避免做错方向）

| 项 | 说明 |
|----|------|
| **new-api 侧要改代码吗** | **不需要改一行业务代码。** 只需设一个环境变量 |
| 唯一改动点 | `TRYINGOPEN_PROXY_FILE` 指向 `proxies.txt` |
| 不要动的东西 | `relay/channel/tryingopen/*.go` 任何逻辑、`setting` 表、生产 DB |
| 谁负责存活 | **你（对接着）**。new-api 不验住宅源，见 §5 |
| 合规 | 节点 `ss_type=vps` 属上游自营 VPS，20 台共用同一密码。是否投产由运营方决定；技术链路本文档已全部打通 |

---

## 1. 现状（已验收，可直接用）

```powershell
cd D:\apk-analysis\fastvpn
```

| 组件 | 状态 | 位置 |
|------|------|------|
| `mihomo.exe` | 需自行放置（从 v2rayN 发行包复制即可） | 仓库根目录 |
| `mihomo_config.yaml` | 已生成，26 个 listeners | 仓库根目录 |
| `portmap.json` | 节点 ↔ socks 端口映射 | 仓库根目录 |
| `nodes.json` | 26 节点全量（20 活 / 5 挪威死 / 1 兜底死） | 仓库根目录 |
| `proxies.txt` | **20 条存活 socks5** | 仓库根目录 |
| `health_loop.py` | 常驻健康检查（双阈值摘除） | 仓库根目录 |

启动转换层（若未在跑）：

```powershell
cd D:\apk-analysis\fastvpn
.\mihomo.exe -f mihomo_config.yaml -d .
# 验证 20 个 socks 端口在监听
(Get-NetTCPConnection -State Listen | ? { $_.LocalPort -ge 24000 -and $_.LocalPort -le 24025 }).Count
```

先跑一轮健康检查，确认 `proxies.txt` 是最新的：

```powershell
python health_loop.py --once
# 期望输出: 探 26 / 在用 20 / 本轮摘除 6
```

---

## 2. 三种部署形态（按你的容器拓扑选一个）

**这是首次对接最常见的失败点**：new-api 在 Docker 里时，容器内的 `127.0.0.1`
是容器自己的 loopback，**不是宿主机**，连不到 mihomo 的 `127.0.0.1:24000`。

### 方案 A：new-api 裸跑在宿主机（最简单，`proxies.txt` 原样可用）

```env
TRYINGOPEN_PROXY_FILE=D:\apk-analysis\fastvpn\proxies.txt
```
无需改动。Linux 裸跑同理，路径换成 `/opt/fastvpn/proxies.txt`。

### 方案 B：new-api 在容器里，mihomo 在宿主机（推荐）

1. 改 `mihomo_config.yaml`，把所有 `listen: 127.0.0.1` 改成 `listen: 0.0.0.0`，
   `allow-lan: true`：

```yaml
allow-lan: true
listeners:
  - {name: "n000_...", type: socks, listen: 0.0.0.0, port: 24000, proxy: "n000_..."}
```

2. 重新生成 `proxies.txt`，把 host 换成容器可达地址：

```powershell
# 生成后整体替换 host
(Get-Content proxies.txt) -replace '127\.0\.0\.1', 'host.docker.internal' | Set-Content proxies.txt
```

3. compose 加 host-gateway（Linux 容器必须，Docker Desktop 默认已有）：

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

### 方案 C：mihomo 进同一 compose 网络

```yaml
services:
  fastvpn-mihomo:
    image: metacubex/mihomo:latest
    volumes:
      - ./mihomo_config.yaml:/root/.config/mihomo/config.yaml:ro
    restart: unless-stopped
```
`proxies.txt` 里的 host 写成 `socks5://fastvpn-mihomo:24000`，且 `allow-lan: true`。

---

## 3. 配置 new-api

```env
# 单文件
TRYINGOPEN_PROXY_FILE=/opt/new-api/fastvpn_proxies.txt

# 或多文件（各自成一张来源卡片, origin=文件名）
TRYINGOPEN_PROXY_FILE=/opt/new-api/proxies.txt,/opt/new-api/residential.txt
```

可选调参（都有合理默认值，**先别动**）：

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `TRYINGOPEN_USE_COOLDOWN_MAP` | `0,30,90,300,900` | 429 冷却阶梯(秒)，按 24h 窗口内使用次数递增 |
| `TRYINGOPEN_PROXY_MAX_USE_PER_DAY` | `0`(不限) | 单代理每日使用上限 |

**生效方式**：`LoadProxies()` 在**启动时**与**配置变更时**调用。
改环境变量必须重启容器；只改 `proxies.txt` 内容不会自动重载 → 要么重启，
要么在管理端触发一次配置保存。

---

## 4. 三层验收（只看到池里有条目 ≠ 流量真走了它）

### 第 1 层：隧道层（转换层自己通）

```powershell
cd D:\apk-analysis\fastvpn
python stress.py
```
判据：`alive` 应为 20 左右，且每行 `exit=节点IP`（出口 IP 必须 == 节点 IP）。

### 第 2 层：池层（new-api 认到了）

```powershell
curl -s http://<new-api>/api/twoapi/proxy_pool -H "Authorization: <admin token>"
```
判据：
- `total` ≥ 20
- 这批条目 `source = "residential"`
- `origin` = `proxies.txt`（或你起的文件名）
- `healthScore = 1.0`

### 第 3 层：**业务层**（必须做，最容易漏）

发一条真实 relay 请求走该渠道，然后**在上游侧核对来源 IP**（或让上游回显 peer IP）。
只看第 2 层有条目就宣称打通 = 伪实现。

---

## 5. 常驻健康检查（必须 deploy，不是可选项）

**为什么必须自己跑**：`proxy_pool.go:1180` 的 `TraceProbes()` 里

```go
if e.source != "free" {
    continue      // 住宅源不做真实出口拨测
}
```

`TRYINGOPEN_PROXY_FILE` 加载的条目 `source` 恒为 `"residential"`，
**new-api 永远不会验它们**。死节点会被反复选中，表现为「渠道高概率超时」。

### 做法一：cron（推荐）

```cron
*/10 * * * * cd /opt/fastvpn && /usr/bin/python3 health_loop.py --once >> health.log 2>&1
```

### 做法二：常驻

```bash
nohup python health_loop.py --interval 600 >> health.log 2>&1 &
```

Windows 免 console 常驻：

```powershell
Start-Process python -ArgumentList "health_loop.py","--interval","600" -WindowStyle Hidden
```

`health_loop.py` 做了什么：

1. 每轮对 26 个 listener 做**真实协议探测**（SS 握手 → 出口 IP → HTTPS）
2. **出口 IP 必须等于节点 IP**，否则判 `exit_mismatch`（防上游把节点偷偷改成中转）
3. **双阈值摘除**：连续 2 轮失败才移出；但「从未通过过」的新节点首轮就不入池
4. 原子重写 `proxies.txt`（`os.replace`，new-api 不会读到半个文件）

> 重写 `proxies.txt` 后仍需让 new-api 重载池子（重启或触发配置保存）。
> 若要免重启，可改用 `TRYINGOPEN_PROXIES` 环境变量 + 定时任务改 env 重启，
> 但代价更大；**推荐做法是每天固定时段重启一次容器**。

---

## 6. 故障排查表

| 症状 | 原因 | 处理 |
|------|------|------|
| 池子 total=0 | 文件路径容器内不可见 / `#` 之外全被跳过 | 容器内 `cat` 一次该文件；确认每行是 `socks5://host:port` |
| total≥20 但全部失败 | 容器连不到 `127.0.0.1:24000` | 走 §2 方案 B/C |
| 渠道偶发超时 | 死节点未被摘除（new-api 不验住宅源） | 部署 §5 health_loop |
| 整池突然全不可用 | 同一代理连续失败 5 次 → 10 分钟**全渠道熔断**（`globalFailThreshold=5`） | 等 10 分钟；减少单代理并发 |
| 上游 429 频繁 | 20 个出口全在美国同一段，被上游按出口限流 | 调 `TRYINGOPEN_USE_COOLDOWN_MAP` 拉长冷却；降并发 |
| 出口 IP 变了 | 上游切换中转 | `health_loop.py` 会判 `exit_mismatch` 自动摘除 |
| 节点全挂 | 上游轮换了 SS 密码 | 重跑 `python pool_cycle.py` 重新收割 |

---

## 7. 池内行为（读源码确认，别猜）

| 行为 | 事实 | 生产影响 |
|------|------|----------|
| 住宅源不拨测 | `TraceProbes()` `if e.source != "free" { continue }` | 存活只能靠 `health_loop.py` |
| 健康权重 | `addSource(..., source="residential", health=1.0)` | 池内最高权重档，会优先被选中 |
| 429 冷却 | 阶梯 `0/30/90/300/900s`，按 24h 使用次数递增，**只冷该渠道** | 端口少时整池迅速冷却 |
| 普通失败 | 冷却 30s + `healthScore *= 0.7` + 权重衰减 | 隧道抖动会拉低权重 |
| 全渠道熔断 | 连续失败 5 次 → 冷却 10 分钟 | 表现为「整池突然没可用」 |
| 每日上限 | `TRYINGOPEN_PROXY_MAX_USE_PER_DAY`，默认不限 | 视额度调整 |
| 多文件 | 逗号分隔，`origin = filepath.Base(file)` | 每个文件一张来源卡片，便于看健康度 |

---

## 8. 红线（不要做）

1. **不要**为提高命中率去改 `TraceProbes` 让它拨测住宅源 —— 会把 20 条串行探测塞进热路径。
2. **不要**把真实节点 IP / 密码 / token 提交进任何仓库（本次已全部脱敏）。
3. **不要**用 `git commit` 自动推送或改生产配置；投产走你们的发布流程。
4. **不要**把 `proxies.txt` 里的 `127.0.0.1` 原样塞进容器（见 §2）。
5. **不要**在生产宿主机上跑 `harvest.py`/`stress.py` 全量扫描 —— 20 并发探活虽轻，但按发布纪律应在 staging 做。

---

## 9. 验收清单

- [ ] `mihomo.exe -f mihomo_config.yaml -d .` 起得来，20 个 socks 端口在监听
- [ ] `python health_loop.py --once` → `在用 20 / 摘除 6`
- [ ] `python stress.py` → 每行 `exit == 节点 IP`
- [ ] new-api 容器内能 `curl --socks5 <host>:24000` 通（先验网络可达，再验业务）
- [ ] `TRYINGOPEN_PROXY_FILE` 已配，重启后池子 total ≥ 20、`source=residential`
- [ ] 业务层发真请求并核对上游侧来源 IP
- [ ] `health_loop.py` 已进 cron/常驻，`health.log` 有滚动输出
- [ ] 摘除逻辑验证过一次（可临时改一个监听端口模拟）

---

## 10. 复现上游（万一节点全挂）

```powershell
cd D:\apk-analysis\fastvpn
python pool_cycle.py            # 收割 → 配置 → 重启 → 压测 → proxies.txt
python health_loop.py --once    # 再刷一次存活清单
```

若报 `KeyError`/解密失败 → 上游换了 PNG key，按 `docs/PROTOCOL.md` §2 重新派生。
