<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Quote } from 'lucide-vue-next'
import { listEvidence } from '@/api/graph.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 知识空间 · 原文引用（page-design §15.3）。
 * 数据源：GET /graph/course/{id}/evidence（available，knowledge.view）。
 * 列表字段：来源文件、页码、引用片段、状态、校验时间（§15.3）。
 * 筛选：全部 / 有效 / 已失效 / 孤立（后端 status 参数真实过滤）。
 * 重新绑定、确认正式、批量检查来源更新依赖治理写契约，如实标注。
 */
const route = useRoute()
const courseId = Number(route.params.courseId)

const status = ref('loading') // loading | ready | empty | error
const forbidden = ref(false)
const items = ref([])
const filter = ref('all') // all | active | stale | orphaned

const filterOptions = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '有效' },
  { value: 'stale', label: '来源失效' },
  { value: 'orphaned', label: '孤立引用' },
]

const statusMeta = {
  active: { label: '有效', tone: 'green' },
  stale: { label: '来源失效', tone: 'red' },
  orphaned: { label: '孤立', tone: 'amber' },
}

const typeLabel = {
  ppt: 'PPT',
  textbook: '教材',
  lecture: '讲义',
  plan: '教案',
  code: '代码规范',
}

const filteredCount = computed(() => items.value.length)

async function load() {
  status.value = 'loading'
  forbidden.value = false
  try {
    const params = filter.value === 'all' ? {} : { status: filter.value }
    const data = await listEvidence(courseId, params)
    items.value = Array.isArray(data?.items) ? data.items : []
    status.value = items.value.length ? 'ready' : 'empty'
  } catch (e) {
    forbidden.value = /403|权限|拒绝/.test(String(e?.message || ''))
    status.value = 'error'
  }
}

function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN')
}

function changeFilter(value) {
  filter.value = value
  load()
}

onMounted(load)
</script>

<template>
  <div class="sfx-evidence">
    <header class="sfx-evidence-head">
      <div>
        <h1 class="sfx-t-title2">原文引用</h1>
        <p class="sfx-t-ui sfx-t-secondary">知识点、讲稿和回答所依赖的原文来源</p>
      </div>
      <div class="sfx-evidence-filters" role="tablist" aria-label="引用状态筛选">
        <button
          v-for="opt in filterOptions"
          :key="opt.value"
          type="button"
          role="tab"
          :aria-selected="filter === opt.value"
          class="sfx-evidence-filter"
          :class="{ 'is-active': filter === opt.value }"
          @click="changeFilter(opt.value)"
        >{{ opt.label }}</button>
      </div>
    </header>

    <SfxSkeleton v-if="status === 'loading'" :lines="5" />

    <SfxError
      v-else-if="status === 'error'"
      :variant="forbidden ? 'forbidden' : 'error'"
      :description="forbidden ? '你当前的身份无法查看原文引用治理数据。' : '原文引用暂时无法读取，请稍后重试。'"
      @retry="load"
    />

    <SfxEmpty
      v-else-if="status === 'empty'"
      :title="filter === 'all' ? '暂无原文引用' : '没有符合筛选的引用'"
      :description="filter === 'all'
        ? '课程资料解析并建立引用后，这里会集中展示每条引用的来源与状态。'
        : '切换其他状态筛选查看。'"
    >
      <template #icon><Quote :size="28" :stroke-width="1.8" /></template>
    </SfxEmpty>

    <template v-else>
      <p class="sfx-t-caption sfx-t-muted">共 {{ filteredCount }} 条</p>
      <div class="sfx-table-wrap">
        <table class="sfx-table">
          <thead>
            <tr>
              <th>来源文件</th><th>类型</th><th>页码</th><th>引用片段</th><th>状态</th><th>记录时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.evidence_id">
              <td class="sfx-evidence-file">{{ item.source_file || '未知来源' }}</td>
              <td><SfxBadge tone="ink">{{ typeLabel[item.evidence_type] ?? item.evidence_type ?? '资料' }}</SfxBadge></td>
              <td class="sfx-mono">{{ item.page_number != null ? `P${item.page_number}` : '—' }}</td>
              <td class="sfx-evidence-snippet sfx-t-sm">{{ item.text_snippet || '（无片段）' }}</td>
              <td>
                <SfxBadge :tone="statusMeta[item.status]?.tone ?? 'neutral'">
                  {{ statusMeta[item.status]?.label ?? item.status }}
                </SfxBadge>
                <p v-if="item.stale_reason" class="sfx-t-caption sfx-evidence-stale">{{ item.stale_reason }}</p>
              </td>
              <td class="sfx-t-caption">{{ formatTime(item.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <p class="sfx-t-caption sfx-t-muted sfx-evidence-note">
        学生端「原文引用」只读；重新绑定、确认正式与批量来源检查属于图谱治理写操作，教师可在候选审核与版本记录中处理。
      </p>
    </template>
  </div>
</template>

<style scoped>
.sfx-evidence {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-6);
}

.sfx-evidence-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.sfx-evidence-filters {
  display: inline-flex;
  gap: var(--space-1);
  background: var(--surface-soft);
  border-radius: var(--radius-md);
  padding: 3px;
}

.sfx-evidence-filter {
  height: 30px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: var(--ui-sm-size);
  font-weight: var(--ui-md-weight);
}

.sfx-evidence-filter:hover { color: var(--ink-700); }
.sfx-evidence-filter.is-active { background: var(--surface-panel); color: var(--ink-900); box-shadow: var(--shadow-xs); }

.sfx-evidence-file { font-weight: 500; max-width: 200px; }

.sfx-evidence-snippet {
  color: var(--text-secondary);
  max-width: 360px;
}

.sfx-evidence-stale { color: var(--red-700); margin-top: 2px; }

.sfx-evidence-note { margin-top: var(--space-2); }
</style>
