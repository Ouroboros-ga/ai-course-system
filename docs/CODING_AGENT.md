# Coding Agent 工作入口

更新时间：2026-07-13。本文件为自动化编码工具提供较完整的导航；根目录 `AGENTS.md` 优先级更高。

## 工作原则

1. 先读 `AGENTS.md`，再读本文件；当前第一阶段以稳定、兼容、可验证、可回滚为先。
2. 每项功能判断必须落到注册路由、调用链、模型、前端调用或测试。历史材料和设计稿不得作为实现证据。
3. 默认隔离外部副作用：使用 `backend/tests/conftest.py`、`backend/tests/fakes.py`、`monkeypatch` 和 FastAPI dependency override；不得在自动化测试中访问真实付费 LLM、TTS、PPT、数字人、生产密钥或生产数据库。
4. 开始任何改动前先执行 `git status --short`。工作区已有的无关修改、未跟踪文件和 stash 一律不撤销、不暂存、不混入提交。
5. 不为了测试或规划而改变公开 API、生产数据库结构、启动方式或用户可见行为。确实无法建立测试时，才考虑最小行为保持型可测试性修改。

## 按任务选择证据

| 任务 | 必读资料 | 代码入口 | 主要回归 |
|---|---|---|---|
| 现状与接口审计 | [功能现状审计表](phase1/功能现状审计表.md)、[API-Service-Model-外部依赖矩阵](phase1/API-Service-Model-外部依赖矩阵.md)、[路由契约基线](phase1/路由契约基线.md) | `backend/app/main.py`、`backend/app/api/v1/endpoints/` | `test_m4a_isolation.py`、`test_m4a_route_contract.py` |
| 教师建课/文档/脚本 | [R2D0 链路审计](refactor/document_kg_v2/R2D0当前文档与图谱链路审计.md) | `document.py::upload_document`、`document_service.py::DocumentService.process_document` | `test_m4b_main_flows.py`、`test_m7_demo_flow.py` |
| 外部服务 | [R1 设计](refactor/R1外部服务适配层设计.md)、[R1 报告](refactor/R1迁移报告.md) | `backend/app/platform/adapters/` | `test_r1_adapters.py`、`test_r1_adapter_migration.py` |
| 数字人/PPT/TTS 长任务 | [R2 盘点](refactor/R2任务现状盘点.md)、R2B/R2C 报告 | `backend/app/platform/tasks/`、相关 endpoint/service | `test_r2_task_runtime.py`、`test_r2b_*`、`test_r2c_tts_batch_task.py` |
| 决赛流程 | [M7 操作脚本](phase1/M7决赛演示操作脚本.md)、[M7 降级手册](phase1/M7故障恢复与降级手册.md) | 教师/学生主路由 | `test_m7_demo_flow.py` |
| 文档智能与图谱后续设计 | `docs/refactor/document_kg_v2/` | 先核对现有 V1 链路，再决定是否另立授权任务 | 先补评测和契约，不直接替换 V1 |

## 已验证的主链边界

- 注册入口：`backend/app/main.py:87-104`。
- 上传主链：`backend/app/api/v1/endpoints/document.py::upload_document` -> `backend/app/services/document_service.py::DocumentService.process_document` -> `Course`、`DoclingDocument`、`CourseScript`、`ScriptNode`。
- TTS：`document.py::_background_synthesize_audio`、`synthesize_node_audio`、`synthesize_all_node_audio`；兼容状态仍是模块级 `tts_generation_status`。
- 学生闭环：`chat.py`、`progress.py`、`prerequisite.py`、`player.py` 与前端 `frontend/src/composables/useStudentLearning.js`。
- M4B/M7 在上传处 fake `DocumentService.process_document`，因此不得把这些测试描述为真实解析质量验证。

## 明确不应误报的能力

`backend/app/api/v1/endpoints/codebench.py`、`graphrag.py`、`cognitive.py`、`agents.py` 未被 `main.py` 注册为主路由；`frontend/src/router/index.js` 未挂接对应产品页。产品二、GraphRAG、BKT/HMM/LSTM 和复杂多智能体均为后续规划，除非新任务明确授权，否则不得实现或宣传为现有能力。

## 文档消费顺序

1. [文档状态审查清单](文档状态审查清单.md) 确认资料状态。
2. `docs/phase1/` 获取已验证事实、测试基线和演示操作。
3. `docs/refactor/` 获取已完成迁移报告或明确标记的未来设计。
4. 根目录 CodeMind/V3.1、赛题和可视化规划文件只能用于产品构想，不可反推代码事实。

提交说明必须记录修改范围、验证命令与结果、已知限制和回滚方法。发现无关工作树变更时，只记录，不清理。
