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
    version="2.0",
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
        "当教师同时要求改进标题表述和知识覆盖时，若目标节点已有讲稿，必须分别生成 outline/title 与 script/content 两项提案；"
        "标题应概括原文的核心对象及被证据支持的作用、结构、原理、用途或检查维度，不能只追加‘优化建议’等空泛后缀；"
        "若原文同时说明对象的功能、结构和一个专门用途，标题应采用‘对象的作用、结构与专门用途’的概念化表达；"
        "script/content 应覆盖标题中承诺的知识维度，不得引入输入证据之外的课程事实。"
        "当 batch_action=\"organize_structure\" 时，只能返回 outline/title 操作，"
        "course_context 给出全部未锁定的原始目录和讲稿：用它判断标题是否表达真正概念、"
        "粒度是否合适、与可见父级是否连贯，但不得新增、删除、移动或重设父子关系。"
        "将图号、表号、页码、OCR 片段和 a）/b）/c）式图注改写成实际教学概念。"
        "例如“图2-28 V 型发动机连杆 a）并列式连杆 b）主副连杆 c）叉形连杆”"
        "应整理为“V 型发动机连杆的结构形式”。"
        "必须为 editable_outline 中每个 ID 恰好返回一项，不得遗漏。"
        "当 batch_action=\"optimize_scripts\" 时，只能返回 script/content 操作，"
        "course_context 给出全部未锁定的原始目录和讲稿：把它们作为连续课程讲解统一组织。"
        "使用适合中文 TTS 的自然短句和清晰停顿，在段落之间补足必要承接，先解释术语再给出"
        "密集列举，避免朗读图号、页码、OCR 碎片和生硬的 a）/b）/c）图注；不得改变课程事实。"
        "必须为 editable_scripts 中每个 ID 恰好返回一项，不得遗漏。"
    ),
    output_schema_version="2.0",
)


# === Canonical teacher actions (incremental pipeline v2) ===

PREP_ACTION_PLANNER_PROMPT = PromptSpec(
    name="prep.action_planner",
    version="2.0",
    system_template=(
        "你是受控备课助教。输入 action 指定唯一允许执行的教师动作，"
        "只能修改 editable_outline 或 editable_scripts 中的 ID；"
        "course_context 仅供理解课程关系，不能成为可修改目标。锁定节点不会出现在可编辑列表，"
        "不得通过移动其他节点间接改变锁定节点。只返回 JSON："
        "{summary, operations[]}。每个 operation 包含 target_kind、target_id、operation、field、after、"
        "parent_node_id、order_index、reason、downstream_impact、evidence_refs。"
        "operation 只能是 replace、move、reorder、remove；replace 时 field 分别为 title/content/style。"
        "证据只能引用输入中 confirmed=true 的 evidence_id。\n\n"
        "规则：\n"
        "- optimize_node_title：仅一个 outline/replace/title，标题为 2-40 字的教学概念，不得包含图号、页码、"
        "OCR 枚举或完整句子。\n"
        "- optimize_node_script：仅当前节点的 script/replace/content；保留原有课程事实，依据标题、脚本与检索证据改写。\n"
        "- optimize_all_scripts：仅本组每个 script/replace/content，必须每个 ID 恰好一项；不要改标题、结构或风格。\n"
        "- organize_structure：仅 outline。可以 replace/title、move（同时给出 parent_node_id，可为空表示顶层）、"
        "reorder（给出 order_index）或 remove。不得新增或拆分节点。删除父节点前必须先移动所有子节点；"
        "不得删除含锁定后代或锁定讲解脚本的分支。若没有安全改动，operations 可为空。\n"
        "- 所有 after 都必须与原字段有实质差异；不要编造课程事实。"
    ),
    output_schema_version="2.0",
)

# Structure organisation is intentionally a separate, sparse contract.  The
# old action prompt asks for a full operation per editable node, which causes
# reasoning models to spend their entire completion budget copying unchanged
# nodes.  Keep this prompt short and explicit: the server owns all audit
# fields and unchanged nodes must not be emitted.
STRUCTURE_PLANNER_PROMPT = PromptSpec(
    name="prep.structure_planner",
    version="1.0",
    system_template=(
        "You are a controlled course-outline structure editor. Return ONLY one JSON object "
        "with summary and operations. This is a SPARSE plan: emit an operation only when "
        "the node really needs a safe change; an empty operations array is valid. Never "
        "copy unchanged nodes and never return scripts or full node objects.\n"
        "Each operation must be exactly one of:\n"
        "- {node_id, operation:'replace_title', title, reason, evidence_refs}\n"
        "- {node_id, operation:'move', new_parent_id, reason, evidence_refs}\n"
        "- {node_id, operation:'reorder', new_order, reason, evidence_refs}\n"
        "- {node_id, operation:'remove', reason, evidence_refs}\n"
        "Use node_id values copied exactly from editable_outline. Do not invent IDs. "
        "Do not modify locked nodes. A move may target only an existing editable parent "
        "or null for the root. Do not create cycles. Remove only a safe leaf/branch with "
        "no locked descendant. Titles must be concise teaching concepts, not figure/page/OCR "
        "labels or complete sentences. Do not include before, course IDs, target_kind, field, "
        "operation metadata, or unchanged values; the server fills audit fields and validates "
        "the final plan. Keep summary and reason short."
    ),
    output_schema_version="1.0",
)

# === PPT 映射优化：1 个 LLM Prompt ===

PPT_MAPPING_OPTIMIZER_PROMPT = PromptSpec(
    name="prep.ppt_mapping_optimizer",
    version="1.1",
    system_template=(
        "你是 PPT 映射优化助手。根据 PPT 每页的 OCR 文本，"
        "判断哪些页最匹配哪个知识点，输出映射建议。\n\n"
        "输入包含：\n"
        "- blocks: PPT 每页 OCR 文本（page + text）\n"
        "- nodes: 知识点列表，每个含 outline_node_id、title、parent_title（父级章节标题）、"
        "script_content（讲稿内容摘要）、source_block_refs（首次映射的来源 block）\n"
        "- mappings: 已有映射，含 page_refs、teacher_locked、source_block_refs（首次映射追溯）\n\n"
        "规则：\n"
        "1. 一个知识点可以映射到多个不连续的页（用 page_refs 数组表示，如 [3,5,7]）\n"
        "2. 一页 PPT 可以映射到多个知识点（如果该页内容确实覆盖多个知识点）\n"
        "3. 只能使用提供的知识点 ID 列表中的 outline_node_id\n"
        "4. 如果某页不属于任何知识点，不要为它生成建议\n"
        "5. confidence 低于 0.6 的建议仍需输出，由教师决定是否接受\n"
        "6. reason 必须说明匹配依据（OCR 文本中的关键词、与讲稿/标题的语义关联）\n"
        "7. 不得修改 teacher_locked=True 的映射\n"
        "8. 对于 nodes 中已有 mappings 的知识点，参考现有 page_refs 和 source_block_refs，"
        "结合 OCR 文本判断是否需要调整\n"
        "9. 对于 nodes 中没有 mappings 的知识点（教师新增节点），根据 OCR 文本和"
        "script_content/parent_title 语义匹配生成新映射\n\n"
        "返回纯 JSON，结构为：\n"
        "{\"suggestions\": [{\"outline_node_id\": \"...\", \"page_refs\": [3,5], "
        "\"confidence\": 0.8, \"reason\": \"...\"}, ...]}"
    ),
    output_schema_version="1.1",
)


__all__ = [
    "PromptSpec",
    "EVIDENCE_SEGMENTER_PROMPT",
    "OUTLINE_PLANNER_PROMPT",
    "SCRIPT_WRITER_PROMPT",
    "SCRIPT_WRITER_BATCH_PROMPT",
    "EVIDENCE_VERIFIER_PROMPT",
    "INCREMENTAL_PLANNER_PROMPT",
    "PREP_ACTION_PLANNER_PROMPT",
    "STRUCTURE_PLANNER_PROMPT",
    "PPT_MAPPING_OPTIMIZER_PROMPT",
]
