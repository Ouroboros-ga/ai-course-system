<script setup>
import { ref } from 'vue'
import { createConstraintRule, normalizeConstraintRule } from '@/app/lib/teachingConstraints.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxField from '@/app/ui/SfxField.vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  members: { type: Array, default: () => [] },
  groups: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const confirmDeleteId = ref('')

const intents = [
  { value: '', label: '全部意图' },
  { value: 'concept_question', label: '概念问答' },
  { value: 'code_debugging', label: '代码诊断' },
  { value: 'learning_guidance', label: '学习引导' },
  { value: 'other', label: '其他' },
]

function replace(index, patch) {
  const next = props.modelValue.map((item, idx) => idx === index ? normalizeConstraintRule({ ...item, ...patch }) : item)
  emit('update:modelValue', next)
}

function addRule() {
  const firstStudent = props.members.find(item => item.role === 'student')
  const firstGroup = props.groups[0]
  const targetType = firstStudent ? 'student' : 'group'
  const targetId = firstStudent?.user_id ?? firstGroup?.group_id ?? ''
  emit('update:modelValue', [...props.modelValue, createConstraintRule({ targetType, targetId })])
}

function requestDelete(ruleId, index) {
  if (confirmDeleteId.value !== ruleId) {
    confirmDeleteId.value = ruleId
    return
  }
  confirmDeleteId.value = ''
  emit('update:modelValue', props.modelValue.filter((_, idx) => idx !== index))
}

function targetOptions(rule) {
  return rule.target_type === 'group'
    ? props.groups.map(item => ({ value: String(item.group_id), label: item.name || item.group_id }))
    : props.members.filter(item => item.role === 'student').map(item => ({ value: String(item.user_id), label: `学生 #${item.user_id}` }))
}

function setDate(index, field, raw) {
  replace(index, { [field]: raw ? new Date(raw).toISOString() : null })
}
</script>

<template>
  <div class="constraint-rules">
    <p v-if="!modelValue.length" class="rules-empty">当前没有对象例外，所有学习者使用课程基线。</p>
    <article v-for="(rule, index) in modelValue" :key="rule.rule_id" class="rule-row">
      <div class="rule-grid">
        <SfxField label="生效对象">
          <div class="rule-target">
            <select class="sfx-select" :disabled="disabled" :value="rule.target_type" @change="replace(index, { target_type: $event.target.value, target_id: '' })">
              <option value="student">学生</option><option value="group">分组</option>
            </select>
            <select class="sfx-select" :disabled="disabled" :value="rule.target_id" @change="replace(index, { target_id: $event.target.value })">
              <option value="">请选择</option>
              <option v-for="item in targetOptions(rule)" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </div>
        </SfxField>
        <SfxField label="强度">
          <select class="sfx-select" :disabled="disabled" :value="rule.level" @change="replace(index, { level: $event.target.value, parameters: {} })">
            <option value="flexible">灵活</option><option value="balanced">均衡</option><option value="strict">严格</option><option value="locked">锁定</option>
          </select>
        </SfxField>
        <SfxField label="意图条件">
          <select class="sfx-select" :disabled="disabled" :value="rule.intent || ''" @change="replace(index, { intent: $event.target.value || null })">
            <option v-for="item in intents" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </SfxField>
        <SfxField label="概念 ID" hint="留空表示不限定知识概念。">
          <input class="sfx-input" :disabled="disabled" :value="rule.concept_id || ''" @input="replace(index, { concept_id: $event.target.value || null })" />
        </SfxField>
        <SfxField label="优先级" hint="数值越大越优先；同优先级再按对象具体度排序。">
          <input class="sfx-input" type="number" min="-1000" max="1000" :disabled="disabled" :value="rule.priority" @change="replace(index, { priority: Number($event.target.value) })" />
        </SfxField>
        <SfxField label="原因" required>
          <input class="sfx-input" :disabled="disabled" :value="rule.reason" @input="replace(index, { reason: $event.target.value })" />
        </SfxField>
        <SfxField label="开始时间" hint="可选。">
          <input class="sfx-input" type="datetime-local" :disabled="disabled" @change="setDate(index, 'effective_from', $event.target.value)" />
        </SfxField>
        <SfxField label="结束时间" hint="可选。">
          <input class="sfx-input" type="datetime-local" :disabled="disabled" @change="setDate(index, 'effective_until', $event.target.value)" />
        </SfxField>
      </div>
      <SfxButton variant="danger" size="sm" :disabled="disabled" @click="requestDelete(rule.rule_id, index)">
        {{ confirmDeleteId === rule.rule_id ? '确认删除？' : '删除规则' }}
      </SfxButton>
    </article>
    <SfxButton variant="secondary" size="sm" :disabled="disabled || (!members.some(item => item.role === 'student') && !groups.length)" @click="addRule">新增对象例外</SfxButton>
  </div>
</template>

<style scoped>
.constraint-rules { display: flex; flex-direction: column; gap: var(--space-4); }
.rules-empty { margin: 0; color: var(--text-muted); }
.rule-row { display: flex; flex-direction: column; align-items: flex-end; gap: var(--space-3); padding: var(--space-4) 0; border-top: var(--border-default); }
.rule-grid { width: 100%; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4); }
.rule-target { display: grid; grid-template-columns: 100px minmax(0, 1fr); gap: var(--space-2); }
@media (max-width: 720px) { .rule-grid { grid-template-columns: 1fr; } }
</style>
