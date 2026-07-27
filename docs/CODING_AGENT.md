# Coding Agent 导航（简版）

> 本文件只提供导航。根目录 [AGENTS.md](../AGENTS.md) 是唯一具约束力的执行规则；与本文件冲突时以 `AGENTS.md` 为准。

## 当前工作入口

- 当前功能事实与缺口：[功能现状审计表](phase1/功能现状审计表.md)
- 当前课程建设目标：[统一课程建设与解析基线](phase1/统一课程建设与解析基线.md)
- 已注册路由：`backend/app/main.py`
- 路由契约：[路由契约基线](phase1/路由契约基线.md)
- 回归范围：[关键业务回归矩阵](phase1/关键业务回归矩阵.md)
- 文档分类：[DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)

## 基本规则

1. 改动前检查 `git status --short`，不覆盖或混入既有无关工作树改动。
2. 先核对路由、调用链、模型、前端消费者和测试，再判断功能是否存在。
3. 所有课程作用域操作经过 Course Access v1；不得以全局 `User.role` 或 `Course.teacher_id` 作为运行时授权替代。
4. 不在测试中调用真实付费服务、生产密钥或生产数据库。
5. 新能力的文档必须明确是已实现、候选、研究还是规划；不得以测试 Fake、Shadow 或设计稿宣称生产效果。
