# Honk Custom GeoData (geosite.dat & geoip.dat)

本项目为基于 upstream **DustinWin/ruleset_geodata**（`mihomo-geodata` 分支）生成的轻量、高效、全自研增强版 `geosite.dat` 与 `geoip.dat` 规则集。

专为 `daeuniverse/honk`（`honk-core`）及各类 V2Ray/Mihomo/Sing-box 规则引擎深度定制与对齐，完全去除所有 BitTorrent / P2P 规则，杜绝 duplicate country_code 冲突，并集成专属自定义分流与防泄露分类。

---

## 一、上游来源与架构设计

1. **核心上游规则库**：
   - GeoSite: `https://raw.githubusercontent.com/DustinWin/ruleset_geodata/mihomo-geodata/geosite-all.dat`
   - GeoIP: `https://raw.githubusercontent.com/DustinWin/ruleset_geodata/mihomo-geodata/geoip.dat`
2. **规则去重与同仓复用**：
   - 直接复用同仓库 `../rules/` 下的 `google.json`、`meta.json`、`fakeipfilter-cn.json` 与 `fakeipfilter-!cn.json`，避免数据重复冗余。
3. **零 BT / P2P 规则原则**：
   - 彻底剥离上游 `TRACKERSLIST`、`BITTORRENT`、`TORRENT` 分类，杜绝 BT 连接占用软路由连接数与机场封号风险。
4. **消除 Duplicate Code 告警**：
   - 严格在合并前去重，确保最终二进制文件中每一个 `country_code` 全局唯一，杜绝 `honk-core` 报 `duplicate geosite/geoip code in asset` 告警。
5. **零依赖自动化构建**：
   - `build_geodata.py` 采用纯 Python 3 标准库编写，无需额外安装 protobuf 编译器或三方库，兼容本地与 GitHub Actions CI。

---

## 二、规则分类明细（Tag 清单）

### 1. GeoSite 分类（共 29 个唯一分类）

| 分类标识 (Tag) | 来源与用途说明 |
| :--- | :--- |
| **`ADS`** | 上游去广告集合（100,000+ 条目） |
| **`PRIVATE`** | 内网与私有域名直连 |
| **`CN`** | 国内域名直连集合（100,000+ 条目） |
| **`APPLE-CN`** | Apple 大陆本地 CDN 加速域名 |
| **`MICROSOFT-CN`**| 微软大陆本地 CDN 加速域名 |
| **`GAMES-CN`** | 国服游戏直连域名 |
| **`YOUTUBE`** | YouTube 全球流媒体服务 |
| **`NETFLIX`** | Netflix 视频流媒体服务 |
| **`SPOTIFY`** | Spotify 音乐流媒体服务 |
| **`PROXY`** | GFW / 海外通用代理域名集（26,000+ 条目） |
| **`AI`** | 国际主流 AI 服务（OpenAI / Anthropic / Gemini 等） |
| **`GOOGLE`** *(定制)* | Google 核心服务域名（**已严格剔除 YouTube**，确保 YouTube 优先分流，源自 `../rules/google.json`，767 条目） |
| **`META`** *(定制)* | Meta / Instagram / WhatsApp / Muse AI / Hatch / OHTTP 网关（源自 `../rules/meta.json`） |
| **`BLOCKHTTPDNS`** *(定制)* | 国内各大应用 HttpDNS 劫持解析阻断域名（源自 `custom/blockhttpdns.json`） |
| **`WEBRTC-STUN`** *(定制)* | 海外 STUN/TURN 域名与正则（`^(?i)stun[0-9]*\.`、Twilio 等，用于精准阻断防真实 IP 泄露） |
| **`DOH-CANARY`** *(定制)* | Apple iCloud Private Relay 屏蔽与 DoH Canary 域名（强制降级本地 DNS） |
| **`BILIBILI`, `TIKTOK`, `DISNEY`, `MAX` 等** | 上游保留的主流平台细分分类 |

### 2. GeoIP 分类（共 6 个唯一分类）

| 分类标识 (Tag) | 来源与用途说明 |
| :--- | :--- |
| **`CN`** | 中国大陆 IP CIDR（9,000+ 网段，含 IPv4 与 IPv6） |
| **`PRIVATE`** | RFC1918、CGNAT、保留私网 IP 段 |
| **`TELEGRAM`** | Telegram 官方数据中心 IP 段 |
| **`BLOCKHTTPDNS`** *(定制)* | 国内各大厂 HttpDNS Anycast IP（41 段精确 CIDR，用于在路由层阻断穿透） |
| **`NETFLIX`** | Netflix CDN 官方 IP 段 |
| **`MEDIA`** | 国际主流流媒体服务器 IP 段 |

---

## 三、Honk (`config.dae`) 引用配置示例

在 `config.dae` 的 `assets` 块中配置订阅直链（依据 honk-core beta.6 规范，仅声明支持的标准字段）：

```dae
assets {
    route: direct
    geodata {
        geosite: 'https://ghfast.top/https://raw.githubusercontent.com/wuziwei/sing-box-config-template/main/honk-rule/geosite.dat'
        geoip: 'https://ghfast.top/https://raw.githubusercontent.com/wuziwei/sing-box-config-template/main/honk-rule/geoip.dat'
        route: direct
    }
}
```

在 `dns.routing.request` 与 `routing` 规则中以轻量标签形式引用：

```dae
# DNS 层
qname(geosite: ads, geosite: blockhttpdns, geosite: doh-canary) -> reject
qname(geosite: private, geosite: cn, geosite: apple-cn, geosite: microsoft-cn, geosite: games-cn) -> alidns
qname(geosite: webrtc-stun) -> reject
qname(geosite: youtube, geosite: netflix, geosite: google, geosite: meta, geosite: spotify, geosite: proxy) -> googledns

# Routing 层
dip(geoip: blockhttpdns) -> block(must)
domain(geosite: ads, geosite: blockhttpdns, geosite: doh-canary) -> block
domain(geosite: private, geosite: cn, geosite: apple-cn, geosite: microsoft-cn, geosite: games-cn) -> direct(must)
domain(geosite: webrtc-stun) -> block
domain(geosite: youtube, geosite: netflix) -> proxy
domain(geosite: google) -> google
domain(geosite: meta) -> meta
domain(geosite: spotify) -> spotify
dip(geoip: telegram) -> proxy
```

---

## 四、本地与 CI 自动化维护

1. **手动构建与自检**：
   ```bash
   python3 honk-rule/build_geodata.py
   ```
2. **离线构建（使用本地缓存）**：
   ```bash
   python3 honk-rule/build_geodata.py --offline
   ```
3. **GitHub Actions 每日定时构建**：
   - 工作流位于 `.github/workflows/sync-honk-geodata.yml`。
   - 每日北京时间 04:30（UTC 20:30，在 04:00 规则同步之后）自动运行，检查上游并自动生成更新推送，带 `[skip ci]` 标签避免构建死循环。
