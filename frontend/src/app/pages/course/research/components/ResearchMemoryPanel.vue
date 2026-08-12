<script setup>
import { ref } from 'vue'
import { BrainCircuit, Database, Search, Sparkles } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

defineProps({
  memories: { type: Array, default: () => [] },
  results: { type: Array, default: () => [] },
  retrievalMode: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['store', 'search'])

const content = ref('')
const tier = ref('long_term')
const importance = ref(0.7)
const query = ref('')

function store() {
  if (!content.value.trim()) return
  emit('store', { content: content.value.trim(), tier: tier.value, importance: Number(importance.value) })
  content.value = ''
}

function search() {
  if (!query.value.trim()) return
  emit('search', { query: query.value.trim(), limit: 8 })
}
</script>

<template>
  <section class="memory-panel" aria-labelledby="memory-title">
    <header class="panel-heading">
      <div>
        <p class="panel-kicker">HarnessEngineer · Memory</p>
        <h2 id="memory-title" class="sfx-t-title2">研究记忆</h2>
      </div>
      <SfxBadge :tone="retrievalMode === 'vector' ? 'green' : 'amber'">
        {{ retrievalMode === 'vector' ? 'Vector' : 'Keyword fallback' }}
      </SfxBadge>
    </header>

    <div class="memory-grid">
      <form class="memory-card" @submit.prevent="store">
        <div class="card-title"><Database :size="18" /><strong>写入记忆</strong></div>
        <label><span>内容</span><textarea v-model="content" maxlength="24000" placeholder="保存后续研究需要反复调用的结论、约束或未决问题。" /></label>
        <div class="field-row">
          <label><span>层级</span><select v-model="tier"><option value="long_term">长期</option><option value="short_term">短期摘要</option></select></label>
          <label><span>重要度</span><select v-model="importance"><option :value="0.9">关键</option><option :value="0.7">重要</option><option :value="0.5">一般</option></select></label>
        </div>
        <SfxButton type="submit" variant="primary" :loading="loading" :disabled="disabled || !content.trim()">
          <template #icon><Sparkles :size="16" /></template>
          写入记忆
        </SfxButton>
      </form>

      <form class="memory-card" @submit.prevent="search">
        <div class="card-title"><Search :size="18" /><strong>检索记忆</strong></div>
        <label><span>研究问题</span><input v-model="query" maxlength="2000" placeholder="例如：RAG 教育实验指标" /></label>
        <SfxButton type="submit" variant="secondary" :loading="loading" :disabled="disabled || !query.trim()">检索</SfxButton>
        <div v-if="!results.length" class="memory-empty"><BrainCircuit :size="28" /><span>输入问题后检索当前工作区记忆。</span></div>
        <ol v-else class="memory-results">
          <li v-for="item in results" :key="item.memory_id">
            <span class="score">{{ Number(item.score || 0).toFixed(2) }}</span>
            <p>{{ item.content }}</p>
          </li>
        </ol>
      </form>
    </div>
  </section>
</template>

<style scoped>
.memory-panel { display: flex; flex-direction: column; gap: var(--space-5); }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); }
.panel-kicker { color: var(--text-muted); font-family: var(--font-mono); font-size: var(--caption-size); margin-bottom: var(--space-1); }
.memory-grid { display: grid; grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr); gap: var(--space-4); }
.memory-card { display: flex; flex-direction: column; align-items: stretch; gap: var(--space-4); padding: var(--space-5); border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--surface-panel); }
.memory-card :deep(.sfx-btn) { align-self: flex-start; }
.card-title { display: flex; align-items: center; gap: var(--space-2); color: var(--ink-900); }
.memory-card label { display: flex; flex: 1; flex-direction: column; gap: var(--space-2); color: var(--text-secondary); font-size: var(--ui-sm-size); }
.field-row { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); }
input, textarea, select { border: 1px solid var(--border-strong); border-radius: var(--radius-md); background: var(--surface-page); color: var(--text-primary); padding: var(--space-3); font: inherit; outline: 0; }
input, select { height: var(--control-height); padding-top: 0; padding-bottom: 0; }
textarea { min-height: 180px; resize: vertical; line-height: 1.6; }
input:focus, textarea:focus, select:focus { border-color: var(--ink-500); box-shadow: 0 0 0 2px var(--ink-100); }
.memory-empty { min-height: 180px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-2); text-align: center; color: var(--text-muted); }
.memory-results { display: flex; flex-direction: column; border-top: 1px solid var(--border-default); }
.memory-results li { display: grid; grid-template-columns: 44px 1fr; gap: var(--space-3); padding: var(--space-3) 0; border-bottom: 1px solid var(--border-default); }
.memory-results p { color: var(--text-secondary); font-size: var(--body-md-size); line-height: 1.5; }
.score { color: var(--ink-700); font-family: var(--font-mono); font-size: var(--caption-size); }
@media (max-width: 900px) { .memory-grid { grid-template-columns: 1fr; } }
</style>

