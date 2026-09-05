/**
 * Nexus 能力接线状态单一真相源（Single Source of Truth）。
 *
 * 背景：
 * 这个产品最容易失控的地方不是"功能少"，而是"界面上写着已接通、实际没接通"。
 * 因此 UI 上任何表示"能力可用"的视觉状态（Chip 高亮、面板内容、按钮可点）
 * 一律不得在模板里硬编码，必须从这里读。
 *
 * 三态语义（对应 UI 上的三种视觉）：
 *   ready     —— 运行时真实具备该能力，且结果会真实影响回答。
 *   wired     —— 能力/数据在后端存在，但 Nexus 尚未把它注入 Agent 上下文通道，
 *                即"数据源是真的，影响链路没通"。UI 必须显示为待接入，不能打勾。
 *   unwired   —— 运行时根本不存在该能力。UI 必须显示为未接入，且不得给出数字。
 *
 * 后端接线后的唯一改动点：把对应条目的 state 改成 'ready'，
 * 并把 integration 字段换成真实契约说明。前端其余代码零改动。
 */

export const CAPABILITY_STATE = {
  READY: 'ready',
  WIRED: 'wired',
  UNWIRED: 'unwired',
}

/**
 * 能力清单。
 *
 * `integration` 字段是写给后端看的落地契约：写清楚"要让它变成 ready，
 * 运行时/后端必须提供什么"。前端不实现这些，只消费 state。
 */
export const NEXUS_CAPABILITIES = {
  course_materials: {
    id: 'course_materials',
    label: '课程资料',
    icon: 'FileText',
    state: CAPABILITY_STATE.READY,
    modes: ['nexus_general', 'nexus_research'],
    // 已接通（M2-B1/B2）：Runtime search_course_materials 工具 → Backend
    // /api/v1/nexus-internal/course-evidence（Course Access v1 门控）→
    // ActiveBundle 证据检索（bundle/graph/citation 可追溯）。
    // course_id 由代理层从请求 context 注入，会话绑定课程后生效。
    integration:
      '已接通：search_course_materials（course_id 来自会话绑定的 context，模型传参不改变范围）。',
  },

  cs_knowledge: {
    id: 'cs_knowledge',
    label: 'CS 知识库',
    icon: 'Database',
    state: CAPABILITY_STATE.READY,
    modes: ['nexus_general', 'nexus_research'],
    // 已接通（M2-B1/B2）：Runtime search_cs_knowledge 工具 → Backend
    // /api/v1/nexus-internal/cs-knowledge → discipline_kb BM25 检索。
    // 集成口径（M2-F1）：当前为关键词（BM25）检索、非向量；词条规模见概览接口。
    integration: '已接通：search_cs_knowledge（关键词检索，权威来源随条目返回）。',
  },

  web_search: {
    id: 'web_search',
    label: 'Web 搜索',
    icon: 'Globe',
    state: CAPABILITY_STATE.READY,
    modes: ['nexus_general', 'nexus_research'],
    integration: '已接通：SearXNG 主通道 + DuckDuckGo 降级。',
  },

  arxiv_papers: {
    id: 'arxiv_papers',
    label: 'arXiv 论文检索',
    icon: 'BookMarked',
    state: CAPABILITY_STATE.READY,
    modes: ['nexus_research'],
    integration: '已接通：search_arxiv_papers。',
  },

  nexuslab_repro: {
    id: 'nexuslab_repro',
    label: 'NexusLab 复现',
    icon: 'FlaskConical',
    state: CAPABILITY_STATE.READY,
    modes: ['nexus_general', 'nexus_research'],
    // 已接通（M4）：run_reproduction 提交 → 受控轮询 job 阶段状态 →
    // 确定性指标判定（PASS/FAIL 不经 LLM）→ 报告 Artifact 下载。
    // Clean Verification（A/B 双环境）仍为 P2+ 候选，`reproducible=true`
    // 不由此能力给出。
    integration:
      '已接通：run_reproduction + GET /nexus/repro/jobs/{id} 轮询 + POST .../report（确定性判定）。',
  },

  file_upload: {
    id: 'file_upload',
    label: '文件上传',
    icon: 'Paperclip',
    state: CAPABILITY_STATE.UNWIRED,
    modes: ['nexus_general', 'nexus_research'],
    // 硬事实：Nexus Runtime 无文件工具、无 artifact 存储（见运行时缺陷清单）。
    // 界面不提供假上传按钮，能力状态在此如实呈现。
    integration:
      '需 Runtime 提供文件工具与 artifact 存储契约后，Composer 才恢复附件入口；在此之前 UI 不渲染上传控件。',
    unwiredHint: '文件上传通道未建立',
  },
}

/**
 * 按模式取能力列表，供 Context Chip 行渲染。
 */
export function capabilitiesForMode(mode) {
  return Object.values(NEXUS_CAPABILITIES).filter(
    (c) => !c.modes || c.modes.includes(mode)
  )
}

export function capabilityById(id) {
  return NEXUS_CAPABILITIES[id] || null
}

export function isCapabilityReady(id) {
  return capabilityById(id)?.state === CAPABILITY_STATE.READY
}

/**
 * 复现执行入口是否可用。
 * 当前恒为 false —— Repro Worker 不存在。
 * 这是"点了会不会真的执行"的唯一判据，UI 与 Approval Gate 都必须消费它。
 */
export function isReproductionExecutable() {
  return isCapabilityReady('nexuslab_repro')
}
