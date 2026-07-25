# Judge0 本地接入与验证

## 当前演示拓扑

Windows 后端通过 VirtualBox NAT 的本机回环端口访问：

```text
backend -> http://127.0.0.1:2358 -> NAT -> Ubuntu OJserver:2358 -> Judge0
```

虚拟机内 Judge0 由 server、worker、PostgreSQL、Redis 四个容器组成。前端只调用
本项目的 `/api/v1/sandbox/*`，绝不能直接请求 Judge0。

## 本机配置

在未提交的 `backend/.env` 中设置：

```dotenv
JUDGE0_ENABLED=true
JUDGE0_API_URL=http://127.0.0.1:2358
```

重启后端后，以登录用户调用 `/api/v1/sandbox/health`。代码执行还要求课程的
`coding_sandbox` capability 和 `experiment.run` 权限；后端继续固定语言白名单、
资源上限并强制 `enable_network=false`。

## 验收与回滚

1. 先在 Windows 执行 `Invoke-RestMethod http://127.0.0.1:2358/languages`。
2. 验证 Python、C 的 Accepted、编译错误、运行错误、超时和内存限制。
3. 用课程成员身份验证后端 API 的权限与跨课程拒绝。
4. 关闭 `JUDGE0_ENABLED` 或课程 capability 即可回滚，不影响普通学习与问答。

当前容器使用 `judge0/judge0:latest`，仅可作为本地 Demo。稳定部署前必须锁定已验证
的镜像 tag/digest、保存 Compose/环境配置、完成隔离与恢复演练；不得开放 2358 到 LAN
或公网。
