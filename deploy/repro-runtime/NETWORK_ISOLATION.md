# F3 实验网络隔离：实现、部署配置与回退方案

> 状态：**未部署生效，不宣称隔离完成**。本批交付实现代码、创建脚本与回退
> 方案；实际建网与容器切换另行确认维护窗口。生效前 run 视图如实记
> `network_isolated=false`（默认 bridge 未隔离）。

## 1. 设计

- 专用实验 bridge 网络（默认名 `nexus-exp-restricted`），与业务网络完全
  分开；现有业务容器/网络零改动。
- 保留公开依赖下载：网络非 `--internal`（出网经宿主 NAT），只在
  `DOCKER-USER` 链按目标 CIDR 阻断：
  - `169.254.169.254/32`（metadata，必阻断）；
  - 宿主业务网段（默认阻断 `10/8、172.16/12、192.168/16`，按实际业务网段
    收紧 `BLOCK_CIDRS`，避免误伤公共依赖源——公共源多为公网 IP，不在
    上述私网段内）；
  - 其他任务：同网络内容器互访属已知限制（见 §4），跨 run 隔离靠“一次
    一容器＋用后回收”（现已实现），不宣称同网互访已阻断。
- DNS：沿用宿主/daemon 默认（`PUBLIC_ALLOW_TCP` 仅文档意图，53 端口出网
  不在 DOCKER-USER 默认阻断范围内；若收紧 DNS，需在维护窗口单独验证
  pip/conda 解析）。

## 2. 部署配置

```bash
# 1) 建网与规则（维护窗口内执行）
bash deploy/repro-runtime/scripts/create-isolated-network.sh apply

# 2) 服务配置（repro-runtime 环境）
REPRO_NETWORK_MAP='{"restricted": "nexus-exp-restricted"}'
REPRO_ISOLATED_NETWORK=nexus-exp-restricted

# 3) 调用方（Nexus intake/scope）：scope.network_profile='restricted'
# 4) 核验：bash deploy/repro-runtime/scripts/verify_host.sh <container> \
#      EXPECT_NETWORK=nexus-exp-restricted
```

生效判定：`GET /sandboxes/{run_id}` 返回 `effective_network ==
nexus-exp-restricted` 且 `network_isolated=true`。

## 3. 回退方案

1. 停止接收新实验（Nexus 侧停调度；进行中 run 自然结束或走 run 级取消）。
2. 确认网络上无容器后执行回退：
   `bash deploy/repro-runtime/scripts/create-isolated-network.sh teardown`
   （有容器即拒绝，防止误断）。
3. 清空 `REPRO_NETWORK_MAP`（或去掉 restricted 条目）并重启
   repro-runtime；新 ensure 回到默认 bridge（`network_isolated=false`）。
4. 回滚验证：抽查新容器 `docker inspect` NetworkMode 为 bridge，且
   `GET /sandboxes/{run_id}` 显示未隔离。

## 4. 已知限制（不掩盖）

- 同受限网络内容器可互访（docker 原生语义）；跨任务隔离当前靠容器
  生命周期（一次一容器、用后回收）＋ CPU/内存/pid 配额，不宣称网络层
  已隔离多租户。
- 规则驻留在宿主 iptables（非 docker 网络对象属性）；宿主 iptables
  被重置（`iptables -F` / daemon 重启）后需重跑 `apply`（幂等，可重入）。
- 公共依赖源若落在被阻断私网段（如内网 PyPI 镜像）会导致安装失败——
  属 fail-closed（pip 报错→排错可见），需在窗口内把内网源加入放行或
  改用公网源，并记录在部署纪要中。
