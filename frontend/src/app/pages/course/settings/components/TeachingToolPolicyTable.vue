<script setup>
import { ref, watch } from 'vue'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const props = defineProps({
  tools: { type: Array, default: () => [] },
  evaluations: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['save'])
const rows = ref([])
watch(() => props.tools, value => { rows.value = value.map(item => ({ ...item })) }, { immediate: true, deep: true })

const labels = {
  graph: '知识图谱', retrieval: '课程检索', cognition: '认知状态', question_bank: '题库',
  experiment: '实验上下文', visualization: '算法可视化', sandbox: '代码沙箱',
  coding_diagnosis: '代码诊断', student_history: '学习历史', student_modeling: '学习者建模',
  recommendation: '学习推荐', conversation_context: '对话上下文', question_generation: '智能出题',
  web_research: '外部研究', trigger_experiment: '触发实验', change_topic: '切换主题',
  learning_event: '平台审计',
}
</script>

<template>
  <div class="tool-policy">
    <div class="tool-table-wrap">
      <table class="tool-table">
        <thead><tr><th>能力</th><th>启用</th><th>确认门槛</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.tool_name">
            <td>{{ labels[row.tool_name] || row.tool_name }}</td>
            <td><input v-model="row.enabled" type="checkbox" :disabled="disabled || row.configurable === false" /></td>
            <td>
              <select v-model="row.confirmation_threshold" class="sfx-select is-compact" :disabled="disabled || row.configurable === false">
                <option value="never">无需确认</option><option value="high_risk_only">仅高风险</option><option value="always">始终确认</option>
              </select>
            </td>
            <td><SfxBadge :tone="row.configurable === false ? 'neutral' : (row.enabled ? 'green' : 'amber')">{{ row.configurable === false ? '平台固定' : (row.enabled ? '已启用' : '已关闭') }}</SfxBadge></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="tool-actions"><SfxButton variant="secondary" size="sm" :disabled="disabled" :loading="saving" @click="emit('save', rows.filter(row => row.configurable !== false))">保存工具策略</SfxButton></div>

    <div class="audit-list">
      <h3>最近约束执行摘要</h3>
      <p v-if="!evaluations.length" class="audit-empty">暂无执行记录。</p>
      <div v-for="item in evaluations.slice(0, 5)" :key="item.trace_id" class="audit-row">
        <span><strong>{{ item.effective_level }}</strong> · 学生 #{{ item.student_id }}</span>
        <span>{{ item.enforcement_status }} · {{ item.decision_codes?.join('、') || '无额外决策码' }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-policy { display: flex; flex-direction: column; gap: var(--space-4); }
.tool-table-wrap { overflow-x: auto; }
.tool-table { width: 100%; border-collapse: collapse; font-size: var(--ui-md-size); }
.tool-table th { text-align: left; background: var(--surface-cool); color: var(--text-secondary); }
.tool-table th, .tool-table td { height: 44px; padding: 0 var(--space-3); border-bottom: var(--border-default); }
.tool-table input { width: 16px; height: 16px; accent-color: var(--ink-700); }
.sfx-select.is-compact { height: 32px; }
.tool-actions { display: flex; justify-content: flex-end; }
.audit-list { display: flex; flex-direction: column; gap: var(--space-2); padding-top: var(--space-3); border-top: var(--border-default); }
.audit-list h3, .audit-empty { margin: 0; }
.audit-empty { color: var(--text-muted); }
.audit-row { display: flex; justify-content: space-between; gap: var(--space-4); padding: var(--space-2) 0; color: var(--text-secondary); font-size: var(--ui-sm-size); }
</style>
