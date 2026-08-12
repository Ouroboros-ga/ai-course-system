<script setup>
import { ref } from 'vue'
import { CheckCircle2, CornerDownRight, GitBranch, PauseCircle, PlayCircle, Plus } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

defineProps({
  scopes: { type: Array, default: () => [] },
  activeScopeId: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['create', 'transition'])
const title = ref('')
const objective = ref('')

function createScope() {
  if (!title.value.trim()) return
  emit('create', { title: title.value.trim(), objective: objective.value.trim(), activate: true })
  title.value = ''
  objective.value = ''
}

function tone(scope) {
  if (scope.status === 'completed') return 'green'
  if (scope.status === 'interrupted') return 'amber'
  return scope.is_active ? 'ink' : 'neutral'
}
</script>

<template>
  <section class="scope-panel" aria-labelledby="scope-title">
    <header class="panel-heading">
      <div>
        <p class="panel-kicker">HarnessEngineer · Scope</p>
        <h2 id="scope-title" class="sfx-t-title2">子任务作用域</h2>
      </div>
      <SfxBadge tone="ink">独立上下文</SfxBadge>
    </header>
    <form class="scope-create" @submit.prevent="createScope">
      <label><span>子任务名称</span><input v-model="title" maxlength="240" placeholder="例如：复核实验指标" /></label>
      <label><span>目标</span><input v-model="objective" maxlength="8000" placeholder="定义该子任务的完成边界" /></label>
      <SfxButton type="submit" variant="primary" :loading="loading" :disabled="disabled || !title.trim()">
        <template #icon><Plus :size="16" /></template>
        创建并进入
      </SfxButton>
    </form>
    <ol class="scope-list">
      <li v-for="scope in scopes" :key="scope.scope_id" class="scope-row" :class="{ 'is-active': scope.scope_id === activeScopeId }">
        <div class="scope-line"><GitBranch v-if="!scope.parent_scope_id" :size="17" /><CornerDownRight v-else :size="17" /></div>
        <div class="scope-copy">
          <strong>{{ scope.title }}</strong>
          <span>{{ scope.objective || '未填写目标' }}</span>
          <small v-if="scope.context_summary">恢复摘要：{{ scope.context_summary }}</small>
        </div>
        <SfxBadge :tone="tone(scope)">{{ scope.status === 'active' ? (scope.is_active ? '当前' : '可切换') : scope.status === 'interrupted' ? '已中断' : '已完成' }}</SfxBadge>
        <div class="scope-actions">
          <SfxButton v-if="scope.status === 'interrupted'" size="sm" variant="secondary" :loading="loading" :disabled="disabled" @click="emit('transition', 'scope_resume', { scope_id: scope.scope_id })">
            <template #icon><PlayCircle :size="15" /></template>恢复
          </SfxButton>
          <SfxButton v-else-if="scope.status !== 'completed' && !scope.is_active" size="sm" variant="secondary" :loading="loading" :disabled="disabled" @click="emit('transition', 'scope_switch', { scope_id: scope.scope_id })">切换</SfxButton>
          <SfxButton v-if="scope.status === 'active' && scope.is_active && scope.parent_scope_id" size="sm" variant="secondary" :loading="loading" :disabled="disabled" @click="emit('transition', 'scope_interrupt', { scope_id: scope.scope_id, context_summary: scope.context_summary || scope.objective })">
            <template #icon><PauseCircle :size="15" /></template>中断
          </SfxButton>
          <SfxButton v-if="scope.status !== 'completed' && scope.parent_scope_id" size="sm" variant="tertiary" :loading="loading" :disabled="disabled" @click="emit('transition', 'scope_complete', { scope_id: scope.scope_id })">
            <template #icon><CheckCircle2 :size="15" /></template>完成
          </SfxButton>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.scope-panel { display: flex; flex-direction: column; gap: var(--space-5); }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); }
.panel-kicker { color: var(--text-muted); font-family: var(--font-mono); font-size: var(--caption-size); margin-bottom: var(--space-1); }
.scope-create { display: grid; grid-template-columns: 220px minmax(0, 1fr) auto; align-items: end; gap: var(--space-3); padding: var(--space-4); border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--surface-panel); }
.scope-create label { display: flex; flex-direction: column; gap: var(--space-2); color: var(--text-secondary); font-size: var(--ui-sm-size); }
input { height: var(--control-height); border: 1px solid var(--border-strong); border-radius: var(--radius-md); background: var(--surface-page); color: var(--text-primary); padding: 0 var(--space-3); font: inherit; outline: 0; }
input:focus { border-color: var(--ink-500); box-shadow: 0 0 0 2px var(--ink-100); }
.scope-list { display: flex; flex-direction: column; border-top: 1px solid var(--border-default); }
.scope-row { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto auto; align-items: center; gap: var(--space-3); padding: var(--space-4) var(--space-2); border-bottom: 1px solid var(--border-default); }
.scope-row.is-active { background: var(--ink-100); }
.scope-line { color: var(--text-muted); }
.scope-copy { display: flex; min-width: 0; flex-direction: column; gap: var(--space-1); }
.scope-copy strong { color: var(--ink-900); font-size: var(--body-md-size); }
.scope-copy span, .scope-copy small { color: var(--text-muted); font-size: var(--caption-size); }
.scope-actions { display: flex; align-items: center; gap: var(--space-1); }
@media (max-width: 960px) { .scope-create { grid-template-columns: 1fr; } .scope-row { grid-template-columns: 24px 1fr; } .scope-row :deep(.sfx-badge), .scope-actions { grid-column: 2; justify-self: start; } }
</style>
