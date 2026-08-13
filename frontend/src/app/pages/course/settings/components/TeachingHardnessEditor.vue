<script setup>
import { computed } from 'vue'
import { CONSTRAINT_LEVELS, CONSTRAINT_SCOPES, normalizeConstraintProfile, summarizeConstraintImpact } from '@/app/lib/teachingConstraints.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxField from '@/app/ui/SfxField.vue'

const props = defineProps({
  modelValue: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const profile = computed(() => normalizeConstraintProfile(props.modelValue))
const impact = computed(() => summarizeConstraintImpact(profile.value))
const scopeLabels = {
  evidence: '证据', response: '回答', context: '上下文', tools: '工具', actions: '教学动作',
}

function updateLevel(level) {
  emit('update:modelValue', normalizeConstraintProfile({ ...props.modelValue, level, parameters: {} }))
}

function updateScope(scope, checked) {
  const scopes = new Set(profile.value.scopes)
  if (checked) scopes.add(scope)
  else if (scopes.size > 1) scopes.delete(scope)
  emit('update:modelValue', { ...profile.value, scopes: [...scopes] })
}

function updateParameter(name, value) {
  emit('update:modelValue', normalizeConstraintProfile({
    ...profile.value,
    parameters: { ...profile.value.parameters, [name]: value },
  }))
}
</script>

<template>
  <div class="constraint-editor">
    <div class="constraint-levels" role="radiogroup" aria-label="约束强度">
      <label v-for="item in CONSTRAINT_LEVELS" :key="item.value" class="constraint-level" :class="{ 'is-selected': profile.level === item.value }">
        <input :checked="profile.level === item.value" type="radio" name="constraint-level" :value="item.value" :disabled="disabled" @change="updateLevel(item.value)" />
        <span>
          <strong>{{ item.label }}</strong>
          <small>{{ item.description }}</small>
        </span>
      </label>
    </div>

    <div class="constraint-scope-row">
      <span class="sfx-t-ui">约束范围</span>
      <label v-for="scope in CONSTRAINT_SCOPES" :key="scope" class="constraint-check">
        <input :checked="profile.scopes.includes(scope)" type="checkbox" :disabled="disabled" @change="updateScope(scope, $event.target.checked)" />
        <span>{{ scopeLabels[scope] }}</span>
      </label>
    </div>

    <div class="constraint-advanced">
      <SfxField label="上下文字符上限" hint="3,000–24,000；超过后按相关性与完整轮次确定性裁剪。">
        <input class="sfx-input" type="number" min="3000" max="24000" step="500" :disabled="disabled" :value="profile.parameters.max_context_chars" @change="updateParameter('max_context_chars', Number($event.target.value))" />
      </SfxField>
      <SfxField label="回答字符上限" hint="300–4,000；由服务端最终截断。">
        <input class="sfx-input" type="number" min="300" max="4000" step="100" :disabled="disabled" :value="profile.parameters.max_answer_chars" @change="updateParameter('max_answer_chars', Number($event.target.value))" />
      </SfxField>
      <SfxField label="证据条数上限" hint="1–20 条。">
        <input class="sfx-input" type="number" min="1" max="20" :disabled="disabled" :value="profile.parameters.max_evidence" @change="updateParameter('max_evidence', Number($event.target.value))" />
      </SfxField>
      <SfxField label="最少课程证据" hint="严格与锁定模式至少为 1。">
        <input class="sfx-input" type="number" min="0" max="3" :disabled="disabled" :value="profile.parameters.min_course_evidence" @change="updateParameter('min_course_evidence', Number($event.target.value))" />
      </SfxField>
    </div>

    <p class="constraint-impact" role="status"><SfxBadge tone="ink">当前影响</SfxBadge><span>{{ impact }}</span></p>
  </div>
</template>

<style scoped>
.constraint-editor { display: flex; flex-direction: column; gap: var(--space-5); }
.constraint-levels { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: var(--border-default); border-radius: var(--radius-md); overflow: hidden; }
.constraint-level { display: flex; gap: var(--space-3); padding: var(--space-4); cursor: pointer; background: var(--surface-panel); }
.constraint-level:nth-child(odd) { border-right: var(--border-default); }
.constraint-level:nth-child(-n + 2) { border-bottom: var(--border-default); }
.constraint-level.is-selected { background: var(--ink-100); color: var(--ink-900); }
.constraint-level input, .constraint-check input { accent-color: var(--ink-700); }
.constraint-level span { display: flex; flex-direction: column; gap: var(--space-1); }
.constraint-level small { color: var(--text-secondary); line-height: var(--ui-sm-line); }
.constraint-scope-row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-4); }
.constraint-check { display: inline-flex; align-items: center; gap: var(--space-2); font-size: var(--ui-md-size); }
.constraint-advanced { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4); }
.constraint-impact { margin: 0; display: flex; align-items: center; gap: var(--space-3); color: var(--text-secondary); }
@media (max-width: 720px) { .constraint-levels, .constraint-advanced { grid-template-columns: 1fr; } .constraint-level { border-right: 0 !important; border-bottom: var(--border-default); } }
</style>
