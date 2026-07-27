# AI 互动智课系统

本仓库是本地原型 Demo：将课程资料、课程建设、学习、练习、代码实验、可信检索、教学 Agent 和媒体能力逐步接入同一教学系统。

当前处于快速实现与验证阶段。功能是否可用必须以注册路由、真实调用链、数据库模型和测试为准；历史比赛材料、旧设计稿、Shadow 报告与研究文档不构成功能完成证明。

## 快速入口

- [开发与安全规则](AGENTS.md)
- [文档导航](docs/DOCUMENTATION_INDEX.md)
- [当前功能审计](docs/phase1/功能现状审计表.md)
- [统一课程建设与解析基线](docs/phase1/统一课程建设与解析基线.md)
- [运行说明](docs/RUN.md)

## 当前架构方向

```text
课程资料
→ 统一上传与版本化对象存储
→ 解析任务 / DocumentIR / Evidence
→ 可信课程检索、课程图谱与教学结构候选
→ 教师审核、编辑与发布
→ 学生学习、练习、代码实验和教学 Agent
```

课程授权统一遵循 Course Access v1。学生代码仅可通过独立 Judge0 沙箱执行；外部 LLM、OCR、TTS、PPT 和数字人服务均通过独立适配层或任务服务接入。

## 文档状态

- `docs/phase1/`：当前 Demo 的审计、契约、运行与实施基线。
- `docs/research/`、`research/`：离线研究与实验。
- `docs/refactor/`：重构、Shadow、迁移和评审历史。
- `docs/archive/`：历史材料，不作为当前实现依据。
