"""Prep Agent Prompt 集中管理。

使用 PromptSpec 对象化封装，便于版本追踪、A/B 测试和审计。
每次 LLM 调用记录 prompt_name、prompt_version、output_schema_version。

Prompt 文本保持与现有 Service 中的语义完全一致，不修改 Prompt 语义。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptSpec:
    """单个 Prompt 的元数据与模板。

    Attributes:
        name: Prompt 唯一标识（用于审计和日志）
        version: Prompt 版本号（语义变更时递增）
        system_template: System prompt 文本
        output_schema_version: 输出 Schema 版本号
    """

    name: str
    version: str
    system_template: str
    output_schema_version: str


# === Initial 链路：4 个 LLM Prompt + 1 个确定性编译阶段 ===

EVIDENCE_SEGMENTER_PROMPT = PromptSpec(
    name="prep.evidence_segmenter",
    version="1.0",
    system_template=(
        "你是 EvidenceSegmenter。只根据材料确定主题边界、标题、例子和练习。"
        "每个 evidence_id 必须来自输入。"
    ),
    output_schema_version="1.0",
)

OUTLINE_PLANNER_PROMPT = PromptSpec(
    name="prep.outline_planner",
    version="1.0",
    system_template=(
        "你是 OutlinePlanner。为首次智能备课生成 chapter → section → knowledge_point "
        "的课程树和 prerequisite 候选，不生成讲稿。chapter 必须无父节点，section 必须归属 "
        "chapter，knowledge_point 必须归属 section。不要把图号、图注、零件清单、整段正文、"
        "页眉页脚或重复标题当作知识点。所有候选必须引用输入 Evidence。"
    ),
    output_schema_version="1.0",
)

SCRIPT_WRITER_PROMPT = PromptSpec(
    name="prep.script_writer",
    version="1.0",
    system_template=(
        "你是 ScriptWriter。只为一个知识点生成 TeachingScriptNode。段落之间用两个换行分隔，"
        "paragraph_evidence 必须逐段对应，不能写无证据课程事实。"
    ),
    output_schema_version="1.0",
)

SCRIPT_WRITER_BATCH_PROMPT = PromptSpec(
    name="prep.script_writer_batch",
    version="1.0",
    system_template=(
        "你是 ScriptWriter。一次为给定的全部知识点生成 TeachingScriptNode。"
        "每个脚本必须绑定输入 Evidence；不要生成候选列表之外的知识点。"
    ),
    output_schema_version="1.0",
)

EVIDENCE_VERIFIER_PROMPT = PromptSpec(
    name="prep.evidence_verifier",
    version="1.0",
    system_template=(
        "你是 EvidenceVerifier。逐项检查结论和段落是否被 Evidence 支撑。"
        "无法支撑就标记 needs_review 或 failed，不得替作者补证据。"
    ),
    output_schema_version="1.0",
)

# compile_patch 阶段是确定性编译，无 Prompt。

# === Incremental 链路：1 个 LLM Prompt ===

INCREMENTAL_PLANNER_PROMPT = PromptSpec(
    name="prep.incremental_planner",
    version="1.0",
    system_template=(
        "你是受控备课 Agent。只能对 editable_outline 和 editable_scripts 中的 ID 提出修改；"
        "不得生成、删除或移动节点，不得引用未提供的课程事实，不得修改任何锁定内容。"
        "返回纯 JSON，结构为 {summary, operations[]}；每项包含 target_kind, target_id, "
        "field, after, reason, downstream_impact, evidence_refs。"
        "证据只能使用已提供且 confirmed=true 的 evidence_id。"
        "target_kind 必须严格使用英文字符串 \"outline\" 或 \"script\"，"
        "不能使用同义词、中文或节点类型；"
        "field 必须严格使用英文字符串 \"title\"、\"content\" 或 \"style\"；"
        "target_id 必须从输入中原样复制。"
        "editable_scripts.content 是允许改写的课程事实来源；可以在不改变事实含义的前提下"
        "重组、简化和改写其表达。"
        "如果没有 confirmed evidence，evidence_refs 使用空数组即可，不得因此保留原文不变。"
        "当教师明确要求改写时，after 必须与原字段有实质差异，不能提交原文不变的空操作。"
        "示例：{\"summary\":\"...\",\"operations\":[{\"target_kind\":\"script\","
        "\"target_id\":\"输入中的 script id\",\"field\":\"content\",\"after\":\"...\","
        "\"reason\":\"...\",\"downstream_impact\":\"...\",\"evidence_refs\":[]}]}。"
        "如果教师要求只生成一项，operations 必须恰好包含一项。"
    ),
    output_schema_version="1.0",
)

# === PPT 映射优化：1 个 LLM Prompt ===

PPT_MAPPING_OPTIMIZER_PROMPT = PromptSpec(
    name="prep.ppt_mapping_optimizer",
    version="1.0",
    system_template=(
        "你是 PPT 映射优化助手。根据 PPT 每页的 OCR 文本，"
        "判断每页最匹配哪个知识点，输出映射建议。\n\n"
        "规则：\n"
        "1. 每页只能映射到一个知识点\n"
        "2. 只能使用提供的知识点 ID 列表\n"
        "3. 如果某页不属于任何知识点，不要为它生成建议\n"
        "4. confidence 低于 0.6 的建议仍需输出，由教师决定是否接受\n"
        "5. reason 必须说明匹配依据（OCR 文本中的关键词）\n"
        "6. 不得修改 teacher_locked=True 的映射\n\n"
        "返回纯 JSON，结构为 {suggestions: [PptMappingSuggestion, ...]}"
    ),
    output_schema_version="1.0",
)


__all__ = [
    "PromptSpec",
    "EVIDENCE_SEGMENTER_PROMPT",
    "OUTLINE_PLANNER_PROMPT",
    "SCRIPT_WRITER_PROMPT",
    "SCRIPT_WRITER_BATCH_PROMPT",
    "EVIDENCE_VERIFIER_PROMPT",
    "INCREMENTAL_PLANNER_PROMPT",
    "PPT_MAPPING_OPTIMIZER_PROMPT",
]
