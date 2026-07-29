<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { History } from 'lucide-vue-next'
import { diffSnapshots, listSnapshots, publishReviewedSnapshot, rollbackSnapshot } from '@/api/graph.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxDrawer from '@/app/ui/SfxDrawer.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 知识空间 · 版本记录（page-design §15.5，仅教师）。
 * 数据源（available）：GET /graph/course/{id}/snapshots、snapshots/diff、
 * POST rollback/{snapshot_id}。
 * 版本对比展示新增/删除/修改（§15.5）；回滚前必须说明影响并二次确认。
 */
const route = useRoute()
const courseId = Number(route.params.courseId)

const status = ref('loading')
const forbidden = ref(false)
const items = ref([])

// 对比抽屉
const compareOpen = ref(false)
const compareA = ref('')
const compareB = ref('')
const diffResult = ref(null)
const diffLoading = ref(false)
const diffError = ref('')

// 回滚
const rollbackTarget = ref(null)
const rollingBack = ref(false)
const publishing = ref(false)
const actionError = ref('')

const statusMeta = {
  rolled_back: { label: '已回滚', tone: 'neutral' },
  published: { label: '正式发布', tone: 'green' },
  superseded: { label: '已被取代', tone: 'neutral' },
  draft: { label: '草稿', tone: 'amber' },
}

const sortedItems = computed(() =>
  [...items.value].sort((a, b) => new Date(b.created_at ?? 0) - new Date(a.created_at ?? 0)),
)

async function load() {
  status.value = 'loading'
  forbidden.value = false
  try {
    const data = await listSnapshots(courseId)
    items.value = Array.isArray(data?.items) ? data.items : []
    status.value = 'ready'
  } catch (e) {
    forbidden.value = /403|权限|拒绝/.test(String(e?.message || ''))
    status.value = 'error'
  }
}

function snapId(snap) {
  return snap.snapshot_id ?? snap.id
}

function openCompare() {
  compareA.value = sortedItems.value[1] ? snapId(sortedItems.value[1]) : ''
  compareB.value = sortedItems.value[0] ? snapId(sortedItems.value[0]) : ''
  diffResult.value = null
  diffError.value = ''
  compareOpen.value = true
}

async function runDiff() {
  if (!compareA.value || !compareB.value || compareA.value === compareB.value) {
    diffError.value = '请选择两个不同的快照进行对比。'
    return
  }
  diffLoading.value = true
  diffError.value = ''
  diffResult.value = null
  try {
    diffResult.value = await diffSnapshots(courseId, compareA.value, compareB.value)
  } catch (e) {
    diffError.value = e?.message || '对比失败，请稍后重试。'
  } finally {
    diffLoading.value = false
  }
}

function diffList(key) {
  const group = key.startsWith('relation_') ? diffResult.value?.relations : diffResult.value?.nodes
  const value = group?.[key.replace(/^relation_/, '')]
  return Array.isArray(value) ? value : []
}

async function publishReviewed() {
  if (publishing.value) return
  publishing.value = true
  actionError.value = ''
  try {
    await publishReviewedSnapshot(courseId)
    await load()
  } catch (e) {
    const detail = e?.response?.data?.detail
    actionError.value = detail?.message || e?.message || '发布前校验未通过，请先完成候选审核和 Evidence 确认。'
  } finally {
    publishing.value = false
  }
}

function askRollback(snap) {
  rollbackTarget.value = snap
  actionError.value = ''
}

async function confirmRollback() {
  if (!rollbackTarget.value || rollingBack.value) return
  rollingBack.value = true
  actionError.value = ''
  try {
    await rollbackSnapshot(courseId, snapId(rollbackTarget.value))
    rollbackTarget.value = null
    await load()
  } catch (e) {
    actionError.value = e?.message || '回滚失败，请稍后重试。'
  } finally {
    rollingBack.value = false
  }
}

function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN')
}

onMounted(load)
</script>

<template>
  <div class="sfx-snapshots">
    <header class="sfx-snapshots-head">
      <div>
        <h1 class="sfx-t-title2">版本记录</h1>
        <p class="sfx-t-ui sfx-t-secondary">图谱快照版本、差异对比与回滚</p>
      </div>
      <SfxButton v-if="items.length >= 2" variant="secondary" size="sm" @click="openCompare">
        对比版本
      </SfxButton>
      <div class="sfx-snapshots-head-actions">
        <SfxButton variant="primary" size="sm" :loading="publishing" @click="publishReviewed">
          发布已审核图谱
        </SfxButton>
      </div>
    </header>

    <SfxSkeleton v-if="status === 'loading'" :lines="5" />

    <p v-if="actionError && status !== 'loading'" class="sfx-snapshots-error sfx-t-ui" role="alert">{{ actionError }}</p>

    <SfxError
      v-else-if="status === 'error'"
      :variant="forbidden ? 'forbidden' : 'error'"
      :description="forbidden ? '版本记录需要课程的知识治理权限（教师）。' : '版本记录暂时无法读取，请稍后重试。'"
      @retry="load"
    />

    <SfxEmpty
      v-else-if="!items.length"
      title="还没有图谱快照"
      description="图谱发布会形成不可变快照；教师确认候选后可在知识治理流程中发布新版本。"
    >
      <template #icon><History :size="28" :stroke-width="1.8" /></template>
    </SfxEmpty>

    <template v-else>
      <p v-if="actionError" class="sfx-snapshots-error sfx-t-ui" role="alert">{{ actionError }}</p>
      <div class="sfx-table-wrap">
        <table class="sfx-table">
          <thead>
            <tr><th>版本</th><th>状态</th><th>创建时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="snap in sortedItems" :key="snapId(snap)">
              <td class="sfx-mono">{{ snap.label || String(snapId(snap)).slice(0, 12) }}</td>
              <td>
                <SfxBadge :tone="statusMeta[String(snap.status).toLowerCase()]?.tone ?? 'neutral'">
                  {{ statusMeta[String(snap.status).toLowerCase()]?.label ?? snap.status }}
                </SfxBadge>
              </td>
              <td class="sfx-t-caption">{{ formatTime(snap.created_at) }}</td>
              <td>
                <SfxButton
                  v-if="String(snap.status).toLowerCase() !== 'published'"
                  variant="danger"
                  size="sm"
                  @click="askRollback(snap)"
                >回滚到此版本</SfxButton>
                <span v-else class="sfx-t-caption sfx-t-muted">当前发布版本</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- 版本对比抽屉 -->
    <SfxDrawer :open="compareOpen" title="版本对比" :width="640" @close="compareOpen = false">
      <div class="sfx-diff-form">
        <div class="sfx-diff-selects">
          <label class="sfx-t-caption">
            基线版本 A
            <select v-model="compareA" class="sfx-select">
              <option value="" disabled>选择快照</option>
              <option v-for="snap in sortedItems" :key="snapId(snap)" :value="snapId(snap)">
                {{ snap.label || String(snapId(snap)).slice(0, 12) }}（{{ formatTime(snap.created_at) }}）
              </option>
            </select>
          </label>
          <label class="sfx-t-caption">
            对比版本 B
            <select v-model="compareB" class="sfx-select">
              <option value="" disabled>选择快照</option>
              <option v-for="snap in sortedItems" :key="snapId(snap)" :value="snapId(snap)">
                {{ snap.label || String(snapId(snap)).slice(0, 12) }}（{{ formatTime(snap.created_at) }}）
              </option>
            </select>
          </label>
        </div>
        <SfxButton variant="primary" size="sm" :loading="diffLoading" @click="runDiff">开始对比</SfxButton>
      </div>

      <p v-if="diffError" class="sfx-snapshots-error sfx-t-ui" role="alert">{{ diffError }}</p>

      <template v-if="diffResult">
        <section class="sfx-diff-group">
          <h3 class="sfx-t-ui sfx-diff-heading"><SfxBadge tone="green">新增</SfxBadge> {{ diffList('added').length }} 项</h3>
          <ul v-if="diffList('added').length" class="sfx-diff-list">
            <li v-for="(d, i) in diffList('added')" :key="i" class="sfx-t-sm">{{ d.title ?? d.name ?? d.id ?? JSON.stringify(d) }}</li>
          </ul>
        </section>
        <section class="sfx-diff-group">
          <h3 class="sfx-t-ui sfx-diff-heading"><SfxBadge tone="red">删除</SfxBadge> {{ diffList('removed').length }} 项</h3>
          <ul v-if="diffList('removed').length" class="sfx-diff-list">
            <li v-for="(d, i) in diffList('removed')" :key="i" class="sfx-t-sm">{{ d.title ?? d.name ?? d.id ?? JSON.stringify(d) }}</li>
          </ul>
        </section>
        <section class="sfx-diff-group">
          <h3 class="sfx-t-ui sfx-diff-heading"><SfxBadge tone="amber">修改</SfxBadge> {{ diffList('modified').length }} 项</h3>
          <ul v-if="diffList('modified').length" class="sfx-diff-list">
            <li v-for="(d, i) in diffList('modified')" :key="i" class="sfx-t-sm">{{ d.title ?? d.name ?? d.id ?? JSON.stringify(d) }}</li>
          </ul>
        </section>
        <section class="sfx-diff-group">
          <h3 class="sfx-t-ui sfx-diff-heading"><SfxBadge tone="green">关系新增</SfxBadge> {{ diffList('relation_added').length }} 项</h3>
          <h3 class="sfx-t-ui sfx-diff-heading"><SfxBadge tone="red">关系删除</SfxBadge> {{ diffList('relation_removed').length }} 项</h3>
          <h3 class="sfx-t-ui sfx-diff-heading"><SfxBadge tone="amber">关系修改</SfxBadge> {{ diffList('relation_modified').length }} 项</h3>
        </section>
        <p v-if="!diffList('added').length && !diffList('removed').length && !diffList('modified').length && !diffList('relation_added').length && !diffList('relation_removed').length && !diffList('relation_modified').length" class="sfx-t-ui sfx-t-secondary">
          两个版本之间没有差异。
        </p>
      </template>
    </SfxDrawer>

    <!-- 回滚确认抽屉（§14.9/§15.5：必须说明影响） -->
    <SfxDrawer
      :open="Boolean(rollbackTarget)"
      title="确认回滚"
      :width="420"
      @close="rollbackTarget = null"
    >
      <p class="sfx-t-body">
        将图谱回滚到版本
        <strong class="sfx-mono">{{ rollbackTarget ? (rollbackTarget.label || String(snapId(rollbackTarget)).slice(0, 12)) : '' }}</strong>。
      </p>
      <ul class="sfx-rollback-impacts sfx-t-ui">
        <li>当前发布快照将被取代，学生端立即看到回滚后的图谱；</li>
        <li>基于当前快照的检索与推荐会切换到回滚版本；</li>
        <li>目标快照保持不可变；回滚只重新激活已有版本，不创建新的内容版本。</li>
      </ul>
      <template #footer>
        <SfxButton variant="tertiary" @click="rollbackTarget = null">取消</SfxButton>
        <SfxButton variant="danger" :loading="rollingBack" @click="confirmRollback">确认回滚</SfxButton>
      </template>
    </SfxDrawer>
  </div>
</template>

<style scoped>
.sfx-snapshots {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-6);
}

.sfx-snapshots-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
}

.sfx-snapshots-head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.sfx-snapshots-error {
  color: var(--red-700);
  background: var(--red-100);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
}

.sfx-diff-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.sfx-diff-selects {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.sfx-diff-selects label {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.sfx-diff-group {
  border-top: 1px solid var(--border-subtle);
  padding-top: var(--space-3);
}

.sfx-diff-heading {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-primary);
  margin-bottom: var(--space-2);
}

.sfx-diff-list {
  margin: 0;
  padding-left: var(--space-5, 20px);
  color: var(--text-secondary);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.sfx-rollback-impacts {
  margin: 0;
  padding-left: var(--space-5, 20px);
  color: var(--text-secondary);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
</style>
