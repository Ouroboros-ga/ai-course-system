# 契约：internal-evidence-api/1.0（公开 V2 Evidence API DTO）

> Owner: P1-09（维护）| 消费方：前端（P1-04 Evidence Viewer）、P1-10（评测）
> 变更审批：P1-00 + 前端 contract review
> 当前版本：`internal-evidence-api/1.0` | 状态：`frozen-major` | 冻结 Gate：G4 ✅
> ADR-0006 §8（G4A/G4B）+ §9（V2 router 约束）

## 1. 目的

冻结后端 V2 Evidence API 响应 ↔ 前端 P1-04 Evidence Viewer 输入的 DTO。这是 Product 1 最后一个未冻结的公开契约（registry 末行「公开 V2 API DTO」），在 G4A 冻结。

DTO 形态（snake_case）镜像 P1-03 已冻结契约（`evidence/1.0`、`citation/1.0`）的 JSON 序列化，并匹配 P1-04 前端 `frontend/src/features/evidence-viewer/contracts.js` 的解析器（解析器同时接受 snake_case 与 camelCase）。

## 2. Endpoint（prefix `/api/v1/evidence-v2`）

所有 endpoint 遵守 ADR-0006 §9：
- **访问控制**：`Depends(admin_only)`，仅 ADMIN 角色；阻断学生 -> 不可跨课程读 Evidence。
- **去敏**：不返回原始本地文件路径；不返回 Provider 原始敏感配置。
- **flag 门禁**：`EVIDENCE_CITATION_MODE` effective 非 `v2_shadow` 时返回 **503 + 结构化 `SHADOW_FEATURE_DISABLED`**（`{detail, flag, effective_mode}`），不返回空 200。
- **G4 数据范围**：返回 DTO-conformant 的空/abstain 响应。真实按文档 Evidence + 页面图像渲染 = G5/G6。G3C shadow trace 是按问题的，非按文档，不在此提供。

| Method | Path | 响应模型 | G4 行为 |
| --- | --- | --- | --- |
| GET | `/documents/{document_id}/evidence?page=` | `EvidenceListResponse` | 空 `evidence_spans` |
| GET | `/documents/{document_id}/citations?page=` | `CitationListResponse` | 空 `citations` |
| POST | `/documents/{document_id}/citations/validate` | `CitationValidationResultDTO` | abstain（no_evidence） |
| GET | `/documents/{document_id}/pages` | `PageListResponse` | 空 `pages` |
| GET | `/documents/{document_id}/pages/{page_number}/image` | `DocumentPageDTO` | 503 PAGE_RENDERING_NOT_AVAILABLE_IN_G4 |

## 3. DTO 字段（snake_case）

### EvidenceSpan
| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `artifact_id` | string | 是 | 稳定 SourceArtifact ID（`art_` 前缀） |
| `document_id` | string | 否（默认 `""`） | 稳定 DocumentIR document ID |
| `unit_id` | string | 否（默认 `""`） | 稳定 DocumentUnit ID |
| `block_id` | string | 是 | 稳定 block ID |
| `version_ref` | string\|null | 否 | 版本/解析 run 引用（staleness） |
| `page_or_slide` | int\|null | 否 | 页/幻灯片号（信息性） |
| `char_start` | int\|null | 否 | 块内零基起始偏移 |
| `char_end` | int\|null | 否 | 块内结束偏移（exclusive） |
| `text_snippet` | string\|null | 否 | 覆盖文本 |
| `score` | float\|null | 否 | 相关性/置信度 |
| `status` | string | 否（默认 `active`） | `active`/`stale`/`suspended` |
| `metadata` | object | 否（默认 `{}`） | 扩展元数据 |

**fail-closed**：缺 `artifact_id` 或 `block_id` -> 前端解析为 `null`（不展示）。

### Citation
| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `key` | string\|null | 否（默认 `null`） | 稳定 citation key；**无证据不得生成伪 key**（null） |
| `statement` | string | 是 | 被引用陈述 |
| `evidence_ref` | string\|null | 否 | 关联 evidence 引用 |
| `page_or_slide` | int\|null | 否 | 页/幻灯片号 |
| `confidence` | float\|null | 否 | 置信度 |
| `metadata` | object | 否（默认 `{}`） | 扩展元数据 |

**fail-closed**：缺 `statement` -> 前端解析为 `null`。

### CitationValidationResult
| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 是 | `verified`/`no_evidence`/... |
| `abstain` | bool | 是 | 无证据支撑时 `true` |
| `abstain_reason` | string\|null | 否 | abstain 原因 |
| `details` | array | 否（默认 `[]`） | 逐 citation 明细 |
| `verified_count` | int | 否（默认 0） | 已验证数 |
| `total_count` | int | 否（默认 0） | 总数 |

### DocumentPageResponse
| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `document_id` | string | 是 | 稳定 document ID |
| `page_number` | int | 是 | 1-based 页号 |
| `image_url` | string | 否（默认 `""`） | 渲染页图像 URL（G4 不渲染） |
| `natural_width` | int | 否（默认 0） | 图像自然宽度（px） |
| `natural_height` | int | 否（默认 0） | 图像自然高度（px） |

## 4. 向后兼容要求

- 旧路径（`/api/v2/evidence`，P1-04 G2 占位）不保留；G4A 起统一为 `/api/v1/evidence-v2`（P1-04 注释明确 deferred 给 P1-09）。
- 旧字段不删改；新字段 optional；旧前端可工作。
- 删字段/改语义/改 ID 算法 = major（需 ADR + schema diff + contract test + P1-00 + 前端 review）；新增 optional = minor。

## 5. fail-closed 规则

- 缺必填字段（`artifact_id`/`block_id`/`statement`/`status`）-> 前端解析为 `null`，不静默展示。
- 无证据不得生成伪 citation key（`key=null`）。
- 坐标高亮 fail-closed（RISK-02）：`parseBoundingBox`/`parsePolygon` 非法返回 `null`（在 P1-04 `contracts.js`）。

## 6. G4 实现说明

- 后端：`backend/app/api/v1/endpoints/evidence_v2.py`（Pydantic response models = DTO；`Depends(admin_only)`；flag-gated 503）。
- 前端：`frontend/src/api/evidence.js`（`API_BASE='/api/v1/evidence-v2'`；raw `fetch`，不改 `utils/request.js`）。
- G4B 挂载：`frontend/src/router/index.js` 独立路由挂载 `EvidenceViewerWithPanel`。
