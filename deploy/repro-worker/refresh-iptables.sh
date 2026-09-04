#!/usr/bin/env bash
# Repro Worker 出站白名单（技术决策补丁 §14/§29：受限网络）
# - 仅作用于 repro_net 网桥（br-*），不影响宿主机与其他容器
# - 允许： Established/Related + GitHub 全家 + PyPI(tuna) + pytorch CPU 轮子源
#   （注意：download.pytorch.org 会重定向到 download-r2.pytorch.org/CloudFront）
# - 其余出站 REJECT；规则可重复执行（幂等刷新）；CDN 换 IP 后重跑本脚本即可
set -eu

BR_ID=$(docker network inspect repro_net --format '{{.Id}}' 2>/dev/null \
  || docker network inspect repro-worker_repro_net --format '{{.Id}}')
BR="br-${BR_ID:0:12}"
echo "bridge: $BR"

# 清掉本脚本此前加的规则（按注释匹配）
while iptables -D DOCKER-USER -m comment --comment "repro-worker-whitelist" 2>/dev/null; do :; done

# 1) 允许已建立连接的回包
iptables -I DOCKER-USER 1 -i "$BR" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT \
  -m comment --comment repro-worker-whitelist

# 2) 允许白名单域名（部署时解析；取 ahostsv4，CloudFront/CDN 多 IP 全量放行）
HOSTS="github.com codeload.github.com objects.githubusercontent.com api.github.com download.pytorch.org download-r2.pytorch.org pypi.tuna.tsinghua.edu.cn"
IPS=$(for h in $HOSTS; do getent ahostsv4 "$h" | awk '{print $1}'; done | sort -u)
COUNT=0
for ip in $IPS; do
  COUNT=$((COUNT+1))
  iptables -I DOCKER-USER 2 -i "$BR" -d "$ip" -j ACCEPT \
    -m comment --comment repro-worker-whitelist
done
echo "allowed ips: $COUNT"

# 3) 该网桥其余出站一律 REJECT（插在 ACCEPT 之后、既有 RETURN 之前）
INSERT_AT=$((COUNT + 2))
iptables -I DOCKER-USER "$INSERT_AT" -i "$BR" -j REJECT \
  -m comment --comment repro-worker-whitelist

echo "== DOCKER-USER repro rules: $(iptables -S DOCKER-USER | grep -c repro-worker-whitelist) entries =="
