# 契约版本规则与变更申请 (Versioning Rules)

> Owner: P1-00。本文件定义 Product 1 所有跨域契约的版本、变更与审批规则。

## 1. 版本号

- 格式：`major.minor`（无 patch；契约不语义化 patch）。
- 起始版本：每个契约首次冻结为 `1.0`。

## 2. 变更分类

| 类型 | 判定 | 审批 | 消费者影响 |
| --- | --- | --- | --- |
| **major** | 删字段；改字段语义；改 ID 算法；扩大默认可见范围；改坐标空间/原点/单位；改删除或审计语义 | ADR + schema diff + contract test + P1-00 + 上表“变更审批”列全部署名 | 消费者必须更新；未知 major fail-closed |
| **minor** | 新增 optional 字段；新增枚举值（不收窄）；新增可选能力声明 | ADR + schema diff + contract test + P1-00 | 旧消费者可继续读；不得破坏旧 minor 读取 |

## 3. 不变量（任何版本都必须保持）

- stable ID 不依赖 timestamp、status、error、retry、run ID、parser run ID、storage path。
- 相同 source bytes + schema version + 规范化规则 => 相同 stable ID。
- 未知 major schema 版本 fail-closed。
- Provider 私有字段只能留在 `raw` / `provenance` 扩展，未经 ADR 不得升级为 canonical 字段。
- 缺失坐标/结构必须显式 warning，不得编造值。
- 无 evidence 不得生成 citation key；无 evidence 不得出强结论。
- 平台安全底线不得被课程策略覆盖。
- 删除/关闭语义不可弱化；跨课程默认不共享记忆。
- 默认 V1 行为不变；新能力默认 disabled / shadow-only。

## 4. 契约变更申请模板

业务 Agent 提交变更时，复制以下模板到 `docs/refactor/product1/adr/00NN-change-<contract>.md`，并通知 P1-00：

```markdown
# ADR-00NN: <契约名> <major|minor> 变更

- 申请人 Agent: P1-0X
- 契约 Owner: P1-0Y
- 当前版本: 1.X
- 申请版本: 1.Y
- 变更类型: major | minor

## 动机
<为什么需要变更；无法用 minor 解决的原因>

## Schema diff
<新增/删除/改语义的字段；before/after>

## 向后兼容影响
<对每个消费方的影响；未知 major 是否 fail-closed>

## Contract test
<新增/修改的 contract test 路径与断言>

## 回滚说明
<关闭 flag / 旧版本回退 / 数据清理路径>

## 审批
- [ ] P1-00
- [ ] P1-10
- [ ] 变更审批列中其他署名方
```

## 5. 登记与发布

- 变更经审批后，P1-00 更新 `contracts/registry.md` 的“当前版本”与“状态”列。
- 契约实现文件头须标注版本与 Owner，例如：`# Contract: DocumentIR v1.0 (Owner: P1-01)`。
- 未经登记的契约字段，消费者不得依赖。
