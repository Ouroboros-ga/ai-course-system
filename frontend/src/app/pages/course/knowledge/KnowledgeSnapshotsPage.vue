<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { History } from 'lucide-vue-next'
import {
  diffKnowledgeBundles,
  listKnowledgeBundles,
  rollbackKnowledgeBundle,
} from '@/api/graph.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxDrawer from '@/app/ui/SfxDrawer.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const route = useRoute()
const courseId = Number(route.params.courseId)
const status = ref('loading')
const forbidden = ref(false)
const items = ref([])
const actionError = ref('')

const compareOpen = ref(false)
const compareA = ref('')
const compareB = ref('')
const diffResult = ref(null)
const diffLoading = ref(false)
const diffError = ref('')

const rollbackTarget = ref(null)
const rollingBack = ref(false)

const sortedItems = computed(() =>
  [...items.value].sort((a, b) => Number(b.version || 0) - Number(a.version || 0)),
)

const statusMeta = {
  ready: { label: '索引就绪', tone: 'green' },
  indexing: { label: '构建索引', tone: 'amber' },
  approved_pending_index: { label: '等待索引', tone: 'amber' },
  failed: { label: '构建失败', tone: 'red' },
  draft: { label: '草稿', tone: 'neutral' },
}

async function load() {
  status.value = 'loading'
  forbidden.value = false
  try {
    const data = await listKnowledgeBundles(courseId)
    items.value = Array.isArray(data) ? data : (data?.items || [])
    status.value = 'ready'
  } catch (error) {
    forbidden.value = /403|权限|拒绝/.test(String(error?.message || ''))
    status.value = 'error'
  }
}

function openCompare() {
  compareA.value = sortedItems.value[1]?.bundle_id || ''
  compareB.value = sortedItems.value[0]?.bundle_id || ''
  diffResult.value = null
  diffError.value = ''
  compareOpen.value = true
}

async function runDiff() {
  if (!compareA.value || !compareB.value || compareA.value === compareB.value) {
    diffError.value = '请选择两个不同的知识包。'
    return
  }
  diffLoading.value = true
  diffError.value = ''
  try {
    diffResult.value = await diffKnowledgeBundles(
      courseId,
      compareA.value,
      compareB.value,
    )
  } catch (error) {
    diffError.value = error?.message || '版本对比失败。'
  } finally {
    diffLoading.value = false
  }
}

function diffList(group, key) {
  const value = diffResult.value?.[group]?.[key]
  return Array.isArray(value) ? value : []
}

function askRollback(bundle) {
  rollbackTarget.value = bundle
  actionError.value = ''
}

async function confirmRollback() {
  if (!rollbackTarget.value || rollingBack.value) return
  rollingBack.value = true
  actionError.value = ''
  try {
    await rollbackKnowledgeBundle(courseId, rollbackTarget.value.bundle_id)
    rollbackTarget.value = null
    await load()
  } catch (error) {
    actionError.value = error?.message || '回滚失败，请确认目标索引仍完整可读。'
  } finally {
    rollingBack.value = false
  }
}

function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN')
}

function itemLabel(item) {
  return item.label || `知识包 v${item.version}`
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="head">
      <div>
        <h1>知识包版本</h1>
        <p>图谱、Evidence、Citation 与 LanceDB 索引以同一版本激活和回滚。</p>
      </div>
      <SfxButton
        v-if="items.length >= 2"
        variant="secondary"
        size="sm"
        @click="openCompare"
      >
        对比版本
      </SfxButton>
    </header>

    <SfxSkeleton v-if="status === 'loading'" :lines="5" />
    <SfxError
      v-else-if="status === 'error'"
      :variant="forbidden ? 'forbidden' : 'error'"
      :description="forbidden ? '需要知识版本查看权限。' : '知识包版本暂时无法读取。'"
      @retry="load"
    />
    <SfxEmpty
      v-else-if="!items.length"
      title="还没有知识包"
      description="教师通过整图后，系统会构建并校验向量索引；校验成功才会出现可激活版本。"
    >
      <template #icon><History :size="28" /></template>
    </SfxEmpty>

    <template v-else>
      <p v-if="actionError" class="error" role="alert">{{ actionError }}</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>版本</th>
              <th>状态</th>
              <th>图谱快照</th>
              <th>向量索引</th>
              <th>批准时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in sortedItems" :key="item.bundle_id">
              <td>
                <strong>{{ itemLabel(item) }}</strong>
                <small>{{ item.bundle_id }}</small>
              </td>
              <td>
                <SfxBadge :tone="item.is_active ? 'green' : (statusMeta[item.status]?.tone || 'neutral')">
                  {{ item.is_active ? '当前激活' : (statusMeta[item.status]?.label || item.status) }}
                </SfxBadge>
              </td>
              <td><code>{{ item.graph_snapshot_id }}</code></td>
              <td><code>{{ item.vector_index_id || '—' }}</code></td>
              <td>{{ formatTime(item.approved_at || item.created_at) }}</td>
              <td>
                <SfxButton
                  v-if="!item.is_active && item.status === 'ready'"
                  variant="danger"
                  size="sm"
                  @click="askRollback(item)"
                >
                  回滚到此版本
                </SfxButton>
                <span v-else class="muted">{{ item.is_active ? '正在服务' : '不可激活' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <SfxDrawer :open="compareOpen" title="知识包差异" :width="640" @close="compareOpen = false">
      <div class="compare-form">
        <label>
          基线版本
          <select v-model="compareA">
            <option value="" disabled>选择知识包</option>
            <option v-for="item in sortedItems" :key="item.bundle_id" :value="item.bundle_id">
              {{ itemLabel(item) }}
            </option>
          </select>
        </label>
        <label>
          目标版本
          <select v-model="compareB">
            <option value="" disabled>选择知识包</option>
            <option v-for="item in sortedItems" :key="item.bundle_id" :value="item.bundle_id">
              {{ itemLabel(item) }}
            </option>
          </select>
        </label>
        <SfxButton variant="primary" size="sm" :loading="diffLoading" @click="runDiff">
          开始对比
        </SfxButton>
      </div>
      <p v-if="diffError" class="error" role="alert">{{ diffError }}</p>
      <div v-if="diffResult" class="diff-grid">
        <section v-for="group in ['nodes', 'relations']" :key="group">
          <h3>{{ group === 'nodes' ? '节点' : '关系' }}</h3>
          <p>新增 {{ diffList(group, 'added').length }}</p>
          <p>删除 {{ diffList(group, 'removed').length }}</p>
          <p>修改 {{ diffList(group, 'modified').length }}</p>
        </section>
      </div>
    </SfxDrawer>

    <SfxDrawer
      :open="Boolean(rollbackTarget)"
      title="确认切换知识包"
      :width="420"
      @close="rollbackTarget = null"
    >
      <p>
        学生图谱、课程检索、后续推荐和助教只读检索将原子切换到
        <strong>{{ rollbackTarget ? itemLabel(rollbackTarget) : '' }}</strong>。
      </p>
      <ul>
        <li>只切换 CourseKnowledgeHead，不删除任何历史 LanceDB。</li>
        <li>旧推荐保留原 Bundle 引用，新推荐使用切换后的 Bundle。</li>
        <li>若目标 manifest 或 COMPLETE 校验失败，激活指针不会改变。</li>
      </ul>
      <template #footer>
        <SfxButton variant="tertiary" @click="rollbackTarget = null">取消</SfxButton>
        <SfxButton variant="danger" :loading="rollingBack" @click="confirmRollback">
          确认切换
        </SfxButton>
      </template>
    </SfxDrawer>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-6); }
.head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.head h1 { margin: 0; font-size: 24px; }
.head p { margin: 6px 0 0; color: var(--text-secondary); }
.table-wrap { overflow-x: auto; border: 1px solid var(--border-subtle); border-radius: var(--radius-md); }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 12px; border-bottom: 1px solid var(--border-subtle); text-align: left; vertical-align: top; }
th { color: var(--text-secondary); font-size: 12px; }
td small, td code { display: block; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
td small { margin-top: 4px; color: var(--text-muted); }
.muted { color: var(--text-muted); font-size: 12px; }
.error { color: var(--red-700); background: var(--red-100); padding: 10px 12px; border-radius: var(--radius-sm); }
.compare-form { display: grid; grid-template-columns: 1fr 1fr auto; align-items: end; gap: 12px; }
.compare-form label { display: grid; gap: 6px; }
.compare-form select { min-height: 38px; border: 1px solid var(--border-default); border-radius: var(--radius-sm); padding: 0 8px; }
.diff-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 18px; }
.diff-grid section { border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 14px; }
@media (max-width: 760px) {
  .head { align-items: flex-start; flex-direction: column; }
  .compare-form, .diff-grid { grid-template-columns: 1fr; }
}
</style>
