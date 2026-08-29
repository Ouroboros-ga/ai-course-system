export const CONSTRAINT_SCOPES = ['evidence', 'response', 'context', 'tools', 'actions']

export const CONSTRAINT_LEVELS = [
  { value: 'flexible', label: '灵活', description: '允许直接引导，但课程事实仍需引用，高风险动作仍需确认。' },
  { value: 'balanced', label: '均衡', description: '课程证据优先，兼顾回答完整度与教学节奏。' },
  { value: 'strict', label: '严格', description: '关闭外部研究，压缩上下文，中高风险动作需确认。' },
  { value: 'locked', label: '锁定', description: '只使用课程证据，采用苏格拉底式引导，所有动作需确认。' },
]

const PROFILE_DEFAULTS = {
  flexible: { max_context_chars: 16000, max_answer_chars: 2400, max_evidence: 12, min_course_evidence: 0, evidence_mode: 'best_effort', guidance_mode: 'direct_guided', confirmation_mode: 'high_risk', external_research: 'tool_policy', require_citations: true },
  balanced: { max_context_chars: 12000, max_answer_chars: 1800, max_evidence: 8, min_course_evidence: 1, evidence_mode: 'course_grounded', guidance_mode: 'guided', confirmation_mode: 'high_risk', external_research: 'tool_policy', require_citations: true },
  strict: { max_context_chars: 8000, max_answer_chars: 1200, max_evidence: 6, min_course_evidence: 1, evidence_mode: 'course_grounded', guidance_mode: 'guided', confirmation_mode: 'medium_and_high', external_research: 'disabled', require_citations: true },
  locked: { max_context_chars: 6000, max_answer_chars: 900, max_evidence: 4, min_course_evidence: 1, evidence_mode: 'course_only', guidance_mode: 'socratic', confirmation_mode: 'all_actions', external_research: 'disabled', require_citations: true },
}

const clamp = (value, min, max) => Math.min(max, Math.max(min, Number(value)))

export function normalizeConstraintProfile(input = {}) {
  const level = Object.hasOwn(PROFILE_DEFAULTS, input.level) ? input.level : 'balanced'
  const parameters = { ...PROFILE_DEFAULTS[level], ...input.parameters }
  parameters.max_context_chars = clamp(parameters.max_context_chars, 3000, 24000)
  parameters.max_answer_chars = clamp(parameters.max_answer_chars, 300, 4000)
  parameters.max_evidence = clamp(parameters.max_evidence, 1, 20)
  parameters.min_course_evidence = clamp(parameters.min_course_evidence, 0, 3)
  parameters.require_citations = true

  if (level === 'strict' || level === 'locked') {
    parameters.external_research = 'disabled'
    parameters.min_course_evidence = Math.max(1, parameters.min_course_evidence)
  }
  if (level === 'locked') {
    parameters.evidence_mode = 'course_only'
    parameters.guidance_mode = 'socratic'
    parameters.confirmation_mode = 'all_actions'
  }

  const requestedScopes = Array.isArray(input.scopes) ? input.scopes : CONSTRAINT_SCOPES
  const scopes = CONSTRAINT_SCOPES.filter(scope => requestedScopes.includes(scope))
  return { level, scopes: scopes.length ? scopes : [...CONSTRAINT_SCOPES], parameters }
}

export function normalizeConstraintRule(input = {}) {
  const normalized = normalizeConstraintProfile(input)
  return {
    ...input,
    level: normalized.level,
    scopes: normalized.scopes,
    parameters: normalized.parameters,
    target_type: input.target_type === 'group' ? 'group' : 'student',
    target_id: String(input.target_id ?? ''),
    reason: String(input.reason || '教师新增约束规则'),
  }
}

export function createConstraintRule({ targetType = 'student', targetId = '' } = {}) {
  const unique = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  return normalizeConstraintRule({
    rule_id: `rule-${unique}`,
    priority: 0,
    target_type: targetType,
    target_id: String(targetId),
    level: 'strict',
    reason: '教师新增约束规则',
  })
}

export function summarizeConstraintImpact(profile) {
  const normalized = normalizeConstraintProfile(profile)
  const p = normalized.parameters
  const evidence = p.evidence_mode === 'course_only' ? '仅课程证据' : p.evidence_mode === 'course_grounded' ? '课程证据优先' : '尽力引用课程证据'
  const research = p.external_research === 'disabled' ? '外部研究关闭' : '外部研究受工具策略控制'
  const confirmation = p.confirmation_mode === 'all_actions' ? '所有动作需确认' : p.confirmation_mode === 'medium_and_high' ? '中高风险动作需确认' : '高风险动作需确认'
  return `${evidence}；${research}；${confirmation}；回答上限 ${p.max_answer_chars} 字。`
}
