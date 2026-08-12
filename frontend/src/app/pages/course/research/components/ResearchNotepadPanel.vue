<script setup>
import { computed, ref, watch } from 'vue'
import { FilePenLine, Save } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const props = defineProps({
  notes: { type: Array, default: () => [] },
  activeScopeId: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['save'])

const selectedId = ref('')
const title = ref('研究笔记')
const content = ref('')
const tags = ref('')
const selected = computed(() => props.notes.find((note) => note.note_id === selectedId.value) || null)

watch(selected, (note) => {
  title.value = note?.title || '研究笔记'
  content.value = note?.content || ''
  tags.value = (note?.tags || []).join('、')
})

function newNote() {
  selectedId.value = ''
  title.value = '研究笔记'
  content.value = ''
  tags.value = ''
}

function save() {
  if (!content.value.trim()) return
  emit('save', {
    note_id: selected.value?.note_id,
    expected_version: selected.value?.version,
    scope_id: props.activeScopeId,
    title: title.value.trim() || '研究笔记',
    content: content.value.trim(),
    tags: tags.value.split(/[、,，]/).map((value) => value.trim()).filter(Boolean),
  })
}
</script>

<template>
  <section class="notepad-panel" aria-labelledby="notepad-title">
    <header class="panel-heading">
      <div>
        <p class="panel-kicker">HarnessEngineer · Notepad</p>
        <h2 id="notepad-title" class="sfx-t-title2">研究笔记</h2>
      </div>
      <SfxBadge tone="ink">持久化</SfxBadge>
    </header>
    <div class="notepad-layout">
      <aside class="note-index">
        <SfxButton size="sm" variant="secondary" @click="newNote">新建笔记</SfxButton>
        <div v-if="!notes.length" class="note-index-empty">暂无笔记</div>
        <label v-for="note in notes" :key="note.note_id" class="note-option" :class="{ 'is-active': selectedId === note.note_id }">
          <input v-model="selectedId" type="radio" name="research-note" :value="note.note_id" />
          <FilePenLine :size="15" />
          <span><strong>{{ note.title }}</strong><small>v{{ note.version }}</small></span>
        </label>
      </aside>
      <form class="note-editor" @submit.prevent="save">
        <label><span>标题</span><input v-model="title" maxlength="300" /></label>
        <label class="content-field"><span>笔记正文</span><textarea v-model="content" maxlength="40000" placeholder="记录证据摘录、假设、冲突点和下一步核验。" /></label>
        <label><span>标签（用顿号分隔）</span><input v-model="tags" maxlength="300" placeholder="evidence、method、dataset" /></label>
        <div class="editor-footer">
          <span class="sfx-t-caption">保存到当前子任务作用域；不写入课程图谱。</span>
          <SfxButton type="submit" variant="primary" :loading="loading" :disabled="disabled || !content.trim()">
            <template #icon><Save :size="16" /></template>
            保存笔记
          </SfxButton>
        </div>
      </form>
    </div>
  </section>
</template>

<style scoped>
.notepad-panel { display: flex; flex-direction: column; gap: var(--space-5); min-height: 0; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); }
.panel-kicker { color: var(--text-muted); font-family: var(--font-mono); font-size: var(--caption-size); margin-bottom: var(--space-1); }
.notepad-layout { display: grid; grid-template-columns: 190px minmax(0, 1fr); min-height: 450px; border: 1px solid var(--border-default); border-radius: var(--radius-md); overflow: hidden; background: var(--surface-panel); }
.note-index { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border-right: 1px solid var(--border-default); background: var(--surface-cool); overflow-y: auto; }
.note-index-empty { color: var(--text-muted); font-size: var(--caption-size); padding: var(--space-4) var(--space-2); }
.note-option { position: relative; display: flex; gap: var(--space-2); align-items: flex-start; padding: var(--space-3); color: var(--text-secondary); cursor: pointer; border: 1px solid transparent; border-radius: var(--radius-sm); }
.note-option input { position: absolute; opacity: 0; }
.note-option.is-active { color: var(--ink-900); background: var(--surface-panel); border-color: var(--border-default); }
.note-option span { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.note-option strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--ui-sm-size); }
.note-option small { color: var(--text-muted); font-family: var(--font-mono); font-size: var(--caption-size); }
.note-editor { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-5); min-height: 0; }
.note-editor label { display: flex; flex-direction: column; gap: var(--space-2); color: var(--text-secondary); font-size: var(--ui-sm-size); }
.content-field { flex: 1; min-height: 240px; }
input, textarea { border: 1px solid var(--border-strong); border-radius: var(--radius-md); background: var(--surface-page); color: var(--text-primary); padding: var(--space-3); font: inherit; outline: 0; }
input { height: var(--control-height); padding-top: 0; padding-bottom: 0; }
textarea { flex: 1; min-height: 220px; resize: vertical; line-height: 1.6; }
input:focus, textarea:focus { border-color: var(--ink-500); box-shadow: 0 0 0 2px var(--ink-100); }
.editor-footer { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); color: var(--text-muted); }
@media (max-width: 900px) { .notepad-layout { grid-template-columns: 1fr; } .note-index { border-right: 0; border-bottom: 1px solid var(--border-default); max-height: 170px; } }
</style>

