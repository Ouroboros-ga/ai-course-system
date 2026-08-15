import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createConstraintRule,
  normalizeConstraintProfile,
  normalizeConstraintRule,
  summarizeConstraintImpact,
} from '../teachingConstraints.js'

test('platform floor wins over a relaxed exception', () => {
  const result = normalizeConstraintRule({
    rule_id: 'student-flex',
    target_type: 'student',
    target_id: '7',
    level: 'flexible',
    reason: 'temporary support',
    parameters: { confirmation_mode: 'high_risk', require_citations: false },
  })

  assert.equal(result.parameters.confirmation_mode, 'high_risk')
  assert.equal(result.parameters.require_citations, true)
})

test('locked profile applies bounded course-only defaults', () => {
  const profile = normalizeConstraintProfile({ level: 'locked' })

  assert.equal(profile.parameters.evidence_mode, 'course_only')
  assert.equal(profile.parameters.guidance_mode, 'socratic')
  assert.equal(profile.parameters.confirmation_mode, 'all_actions')
  assert.equal(profile.parameters.external_research, 'disabled')
  assert.deepEqual(profile.scopes, ['evidence', 'response', 'context', 'tools', 'actions'])
})

test('new rules carry an explicit target and auditable reason', () => {
  const rule = createConstraintRule({ targetType: 'group', targetId: 'grp-a' })

  assert.equal(rule.target_type, 'group')
  assert.equal(rule.target_id, 'grp-a')
  assert.ok(rule.rule_id.startsWith('rule-'))
  assert.equal(rule.reason, '教师新增约束规则')
})

test('impact summary names the major governed surfaces', () => {
  const summary = summarizeConstraintImpact(normalizeConstraintProfile({ level: 'strict' }))

  assert.match(summary, /课程证据/)
  assert.match(summary, /外部研究关闭/)
  assert.match(summary, /中高风险动作需确认/)
})
