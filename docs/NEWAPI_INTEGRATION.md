# Fast VPN Pro → new-api 代理池对接指南

> 面向 new-api 对接会话。读完这一份即可把 20 个可用节点接进 `relay/channel/tryingopen` 代理池。
> 前置：本文档只讲**技术接入**；是否投产见《逆向报告.md》第 7 节合规判定。

---

## 0. 结论

**new-api 侧不需要改一行业务代码。** `relay/channel/tryingopen/proxy_pool.go` 的
`LoadProxies()` 原生支持 `TRYINGOPEN_PROXY_FILE`（逗号分隔多文件，每行 `socks5://host:port`，
`#` 开头跳过），加载后 `source="residential"`、`healthScore=1.0`。
源码注释里就留了这个口子：「住宅清单 + 本地协议转换层……天然是两份来源」。

所以链路是：

```
Fast VPN 云端 /cfg/newuser
   → harvest.py          拿到 20 个 SS 节点
   → build_mihomo.py     生成 mihomo 配置（每节点一个 socks listener）
   → mihomo.exe          单进程映射 25 个 127.0.0.1:24000..24024
   → proxies.txt         只保留测活通过的 socks5 行
   → new-api             TRYINGOPEN_PROXY_FILE=/path/proxies.txt
```

---

## 1. 起转换层

```powershell
cd D:\apk-analysis\fastvpn

# 一次性: 收割 + 生成配置 + 起 mihomo + 压测 + 出 proxies.txt
python pool_cycle.py

# 若本机直连节点网段不通(如本次环境), 需要经已有隧道二次拨号:
python pool_cycle.py --dialer 127.0.0.1:10808
```

`--dialer` 只影响**拨号路径**（本机测试/中转），不改变节点本身；生产环境如果宿主机能直连
`*.digitalocean.com` 网段，**不要**加 `--dialer`，否则多一跳纯增延迟。

产出的 `proxies.txt` 形如：

```
# fast-vpn-pro socks5 pool  2026-10-29 04:54:21  alive=20/26
socks5://127.0.0.1:24000
socks5://127.0.0.1:24001
...
```

---

## 2. 挂到 new-api

```env
TRYINGOPEN_PROXY_FILE=/opt/new-api/proxies.txt
```

- 每行一条，`#` 注释行会被跳过（`addSource` 里 `strings.HasPrefix(raw, "#")`）。
- 支持逗号分隔多文件：`TRYINGOPEN_PROXY_FILE=/opt/new-api/proxies.txt,/opt/new-api/other.txt`
  每个文件在管理端会各自成一张来源卡片（`origin = filepath.Base(file)`）。
- 也可以直接用环境变量塞：`TRYINGOPEN_PROXIES=socks5://127.0.0.1:24000,socks5://127.0.0.1:24001`
  （`origin="env"`，节点多了不好维护，推荐文件）。
- 生效时机：`LoadProxies()` 在**启动时**与**配置变更时**调用。改完环境变量要重启容器；
  改 `proxies.txt` 内容也需要触发一次重载（重启最稳）。

### 2.1 容器网络坑（首次对接最常见的失败点）

new-api 跑在 Docker 里时，容器内的 `127.0.0.1` 是容器自己的 loopback，**不是宿主机**。
mihomo 的 listener 只绑在宿主机 `127.0.0.1:24000` 上，容器访问不到。三选一：

| 方案 | 做法 | 备注 |
|------|------|------|
| A（推荐） | mihomo `listeners[].listen` 改 `0.0.0.0`，容器侧用 `host.docker.internal:24000` | compose 需 `extra_hosts: ["host.docker.internal:host-gateway"]`（Linux） |
| B | new-api 容器 `network_mode: host` | 最省事，但会放弃端口隔离 |
| C | mihomo 进同一 compose 网络，proxies.txt 写 `socks5://fastvpn-mihomo:24000` | 需要改 `allow-lan: true` |

本仓库 `proxies.txt` 默认写 `127.0.0.1`，**同机裸跑（非容器）时才是正确的**。

---

## 3. 池内行为（读源码确认，非猜测）

| 行为 | 事实 | 生产影响 |
|------|------|----------|
| 住宅源不做出口拨测 | `TraceProbes()` 里 `if e.source != "free" { continue }` | 你的 socks5 条目**不会被 new-api 验**；存活必须由 `stress.py` 自己保证 |
| 429 冷却阶梯 | `TRYINGOPEN_USE_COOLDOWN_MAP`（默认 0/30/90/300/900s，按 24h 窗口内使用次数递增） | 20 个端口并发高时整池会迅速冷却 |
| 单代理熔断 | 同一代理连续失败 5 次进 10 分钟全局熔断 | mihomo 抖动会表现为「整池突然没可用」 |
| 每日用量上限 | `TRYINGOPEN_PROXY_MAX_USE_PER_DAY` | 视额度调整 |
| 健康加权 | 住宅源固定 `healthScore=1.0`（池内最高权重档） | 会优先被选中 |

**因此必须做常驻健康检查**：建议 cron 每 10 分钟跑一次
`python stress.py && python -c "..."`（或用 `pool_cycle.py --no-restart`），
把失败节点从 `proxies.txt` 摘掉，**双阈值**（连续 2 轮失败才剔除，单轮抖动常见）。

---

## 4. 三层验证（只看到池里有条目 ≠ 流量真走了它）

1. **隧道层**：`python stress.py` → 每节点出口 IP 必须等于节点 IP，且 HTTP/HTTPS 都通。
2. **池层**：管理端 `/api/twoapi/proxy_pool` 能看到 20 条 `source=residential`、
   `origin=proxies.txt`。
3. **业务层**：发一条真实 relay 请求，在**上游侧**核对来源 IP（或让上游回显 peer IP）。

只做第 2 步就宣称打通是伪实现。

---

## 5. 现实约束（务必读）

| 项 | 值 | 说明 |
|----|-----|------|
| 可用节点数 | **20** | 云端池上限就是 25（20 US + 5 NO），参数扫描无法扩容 |
| 出口国家 | **仅 US** | 单地区池，做多地区分流不够用 |
| 凭证 | **20 台共用同一密码** | 单点吊销即整池失效；上游一改密码全线挂 |
| 节点 IP | 一次性分配，**不轮换** | 连续 30 轮拉取集合完全一致 |
| 上游加密升级风险 | 中 | key 由 PNG LSB 派生，换个图就换 key；harvest 需同步更新 |
| 延迟 | 双跳下 P50 ~1.2s | 直连应该低得多，需在能直连的机器上复测 |

**建议定位**：20 个美国固定 IP 的补充池，不要当主力；与已有住宅/免费源并列，
按 `origin` 区分便于观察健康度。
