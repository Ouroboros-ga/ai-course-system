# SearXNG 搜索主通道（Nexus Web Search）

> 状态：已部署并验收（2026-09-03，用户授权）
> 部署位置：47.99.97.154 `/opt/searxng`，容器 `nexus-searxng`
> 用途：Nexus AI / 后端的免费 Web 搜索主通道，替代付费搜索 API

## 定位

CodeNexus 转型决策（见
[docs/phase1/2026-09-03_CodeNexus转型实施决策.md](../../docs/phase1/2026-09-03_CodeNexus转型实施决策.md)
D3）：Web Search 采用双通道——主通道为本服务（服务器自部署 SearXNG，免费、无 Key、
由服务器 IP 直接发起），下位替代为本机（agent 侧）WebSearch 能力。

## 部署形态

- 镜像：`searxng/searxng:latest`（2026.9.2 版）
- 端口：仅绑定 `127.0.0.1:8888`（与 smartcarb-postgres / smartcarb-paddleocr 的
  本机绑定模式一致，不暴露公网）
- JSON 输出已启用（`search.formats: [html, json]`）；limiter 关闭（仅本机消费）
- 内存上限 512MB；日志轮转 3×10MB；cap_drop ALL

## 引擎配置（境内部署关键项）

服务器为境内阿里云节点，默认启用的引擎（brave/duckduckgo/google cse/startpage/
wikipedia/wikidata）**全部不可达**且每条查询拖满 3s 连接超时。`settings.yml`
按 2026-09-03 实测显式配置：

- **启用**：`360search`（中文，约 0.4s）、`yandex`（中英文，约 1.4s）——
  验收双引擎均稳定返回结果；`bing`、`mojeek` 可达但实测无结果，保留观察；
- **禁用**：上述被墙引擎 + qwant/yahoo；
- 不启用：baidu/sogou（返回 CAPTCHA）、fastbot（拒绝访问）。

若未来新增可用引擎（如代理接入 google），按 name 在 `engines:` 段调整并重启。

## 消费契约（Nexus Runtime / Backend 侧）

```
GET http://127.0.0.1:8888/search?q=<URL编码查询>&format=json&language=zh-CN
```

返回 JSON：`results[]`（title/url/content）、`unresponsive_engines[]`、
`number_of_results` 等。调用方对 `unresponsive_engines` 做容错，检索结果按
AGENTS.md §4.1.5 标记为"补充参考"。

## 运维

```bash
# 更新版本（境内需经镜像源拉取后重打标签，直连 Docker Hub 会失败）
docker pull docker.1panel.live/searxng/searxng:latest
docker tag docker.1panel.live/searxng/searxng:latest searxng/searxng:latest
cd /opt/searxng && docker compose up -d
# 验证
curl -s 'http://127.0.0.1:8888/search?q=test&format=json' | head -c 400
# 回退
cd /opt/searxng && docker compose down
```

## 首次部署步骤（2026-09-03 实际执行）

1. `mkdir -p /opt/searxng` 并上传 `docker-compose.yml`、`settings.yml`；
2. 服务器上生成密钥替换占位符：
   `sed -i "s/REPLACE_WITH_RANDOM_SECRET/<openssl rand -hex 32 结果>/" /opt/searxng/settings.yml`；
3. 经 `docker.1panel.live` 镜像源拉取镜像并重打标签为 `searxng/searxng:latest`
   （服务器 daemon.json 中的加速器均已失效，1panel 为当时唯一可用源）；
4. `docker compose up -d`；
5. 按下节验收。

`settings.yml` 中的密钥只在本机回环消费场景使用；仓库内保持占位符，不提交真实值。

## 验收记录（2026-09-03）

聚合查询（不指定 engines）实测：

| 查询 | 语言 | 结果数 | 延迟 | 失败引擎 |
|---|---|---|---|---|
| 机器学习入门 | zh-CN | 22 | 2.0s | 无 |
| attention is all you need paper | en | 21 | 0.8s | 无 |
| 大语言模型 综述 2025 | zh-CN | 21 | 1.0s | 无 |

结果覆盖 360search 与 yandex 双引擎；英文论文类查询可直接检索到 arXiv
abstract 页面（如 arXiv:1706.03762）。
