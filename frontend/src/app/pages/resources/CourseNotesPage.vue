<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, NotebookPen, StickyNote, Trash2 } from 'lucide-vue-next'
import { deleteNote, listNotes, updateNote } from '@/api/note.js'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

/**
 * 资源库「课程笔记」课程内笔记列表（page-design §20）。
 * 展示当前学生在某课程下保存的全部笔记，按知识点分组，支持编辑与删除。
 */
const route = useRoute()
const router = useRouter()
const courseId = Number(route.params.courseId)
const courseTitle = String(route.query.title || '')

const status = ref('loading')
const notes = ref([])
const error = ref('')
// 编辑态：noteId -> 草稿内容
const editing = ref({})

const sortedNotes = computed(() =>
  [...notes.value].sort((a, b) => {
    const order = (Number(a.node_index) || 0) - (Number(b.node_index) || 0)
    if (order !== 0) return order
    return String(a.updated_at || '').localeCompare(String(b.updated_at || ''))
  })
)

function formatSeconds(sec) {
  if (sec == null || !Number.isFinite(Number(sec))) return ''
  const total = Math.max(0, Math.floor(Number(sec)))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function formatDate(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return ''
  }
}

function noteMeta(note) {
  const parts = []
  if (note.page != null) parts.push(`第 ${note.page} 页`)
  const time = formatSeconds(note.timestamp)
  if (time) parts.push(`播放 ${time}`)
  if (note.updated_at) parts.push(`更新于 ${formatDate(note.updated_at)}`)
  return parts.join(' · ')
}

async function load() {
  status.value = 'loading'
  error.value = ''
  try {
    const data = await listNotes(courseId)
    notes.value = data?.items ?? []
    status.value = notes.value.length ? 'ready' : 'empty'
  } catch (e) {
    error.value = e?.message || '笔记读取失败'
    status.value = 'error'
  }
}

function startEdit(note) {
  editing.value = { ...editing.value, [note.id]: note.content || '' }
}

function cancelEdit(noteId) {
  const next = { ...editing.value }
  delete next[noteId]
  editing.value = next
}

async function saveEdit(note) {
  const content = String(editing.value[note.id] || '').trim()
  // 与学习工作台一致：清空内容视为删除
  if (!content) {
    if (!window.confirm('保存空内容将删除这条笔记，确定吗？')) return
    await removeNote(note)
    return
  }
  try {
    await updateNote(note.id, { content, is_draft: false })
    note.content = content
    note.updated_at = new Date().toISOString()
    cancelEdit(note.id)
  } catch (e) {
    error.value = e?.message || '笔记保存失败'
  }
}

async function removeNote(note) {
  if (!window.confirm('确定删除这条笔记吗？')) return
  try {
    await deleteNote(note.id)
    notes.value = notes.value.filter((item) => item.id !== note.id)
    cancelEdit(note.id)
    if (!notes.value.length) status.value = 'empty'
  } catch (e) {
    error.value = e?.message || '笔记删除失败'
  }
}

function goBack() {
  router.push('/app/resources/notes')
}

onMounted(load)
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header">
      <div class="sfx-page-header-row">
        <SfxButton variant="tertiary" size="sm" @click="goBack"><ArrowLeft :size="15" /> 返回</SfxButton>
        <div>
          <h1 class="sfx-t-title1"><StickyNote :size="22" /> {{ courseTitle || `课程笔记 · ${courseId}` }}</h1>
          <p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">自己保存的 {{ notes.length }} 条笔记，按知识点排列。</p>
        </div>
      </div>
    </header>

    <p v-if="error" class="inline-error sfx-t-ui" role="alert">{{ error }}</p>

    <SfxSkeleton v-if="status === 'loading'" :lines="5" block />
    <SfxError v-else-if="status === 'error'" description="课程笔记暂时无法读取，请稍后重试。" @retry="load" />
    <SfxEmpty v-else-if="status === 'empty'" title="这门课还没有笔记" description="回到课程学习页，点击底部「做笔记」即可记录。">
      <template #icon><NotebookPen :size="28" :stroke-width="1.8" /></template>
      <SfxButton variant="secondary" size="sm" @click="router.push(`/app/course/${courseId}/learn`)">去学习</SfxButton>
    </SfxEmpty>

    <div v-else class="note-list">
      <article v-for="note in sortedNotes" :key="note.id" class="note-card">
        <div class="note-head">
          <div class="note-head-main">
            <h2 class="sfx-t-title3">{{ note.title || '知识点笔记' }}</h2>
            <p class="sfx-t-sm sfx-t-secondary">{{ noteMeta(note) }}</p>
          </div>
          <div class="note-actions">
            <template v-if="editing[note.id] === undefined">
              <SfxButton variant="tertiary" size="sm" @click="startEdit(note)">编辑</SfxButton>
              <SfxButton variant="danger" size="sm" @click="removeNote(note)"><Trash2 :size="14" /></SfxButton>
            </template>
            <template v-else>
              <SfxButton variant="tertiary" size="sm" @click="cancelEdit(note.id)">取消</SfxButton>
              <SfxButton variant="primary" size="sm" @click="saveEdit(note)">保存</SfxButton>
            </template>
          </div>
        </div>
        <textarea
          v-if="editing[note.id] !== undefined"
          v-model="editing[note.id]"
          class="note-editor"
          rows="5"
          placeholder="笔记内容"
        />
        <p v-else class="note-content sfx-t-body">{{ note.content || '（无内容）' }}</p>
      </article>
    </div>
  </div>
</template>

<style scoped>
.sfx-page-header-row { display: flex; align-items: flex-start; gap: var(--space-3); }
.inline-error { color: var(--red-700); margin-bottom: var(--space-3); }
.note-list { display: flex; flex-direction: column; gap: var(--space-3); }
.note-card { padding: var(--space-5); border: 1px solid var(--border-default); border-radius: var(--radius-lg); background: var(--surface-panel); }
.note-head { display: flex; align-items: flex-start; gap: var(--space-3); }
.note-head-main { flex: 1; min-width: 0; }
.note-head-main h2 { margin: 0; }
.note-actions { display: flex; gap: var(--space-1); flex: 0 0 auto; }
.note-content { margin: var(--space-3) 0 0; white-space: pre-wrap; word-break: break-word; }
.note-editor { width: 100%; margin-top: var(--space-3); resize: vertical; padding: var(--space-3); border: 1px solid var(--border-default); border-radius: var(--radius-md); font: inherit; background: var(--surface-panel); }
@media (max-width: 640px) { .note-head { flex-direction: column; } }
</style>
