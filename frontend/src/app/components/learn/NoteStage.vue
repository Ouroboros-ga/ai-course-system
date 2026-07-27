<script setup>
import { computed, ref } from 'vue'
const props = defineProps({ ws: { type: Object, required: true }, anchor: { type: Object, default: null } })
const emit = defineEmits(['exit'])
const saving = ref(false); const error = ref('')
const context = computed(() => props.anchor?.sourceNodeTitle || props.ws.currentNode.value?.title || '当前知识点')
async function finish() { saving.value = true; error.value = ''; const result = await props.ws.finishNote(); saving.value = false; if (!result?.ok) { error.value = result?.error || '笔记尚未保存'; return }; emit('exit') }
</script>
<template><section class="sfx-note-stage"><header><button type="button" @click="emit('exit')">返回课程</button><h2>做笔记 · {{ context }}</h2><span>第 {{ anchor?.sourcePage ?? ws.currentPage.value }} 页</span></header><textarea v-model="ws.currentNote.value" rows="16" placeholder="记录理解、问题、实验结论或原文引用…" /><p v-if="ws.noteSyncError.value" role="alert">{{ ws.noteSyncError.value }}</p><footer><button type="button" @click="emit('exit')">保留草稿</button><button type="button" :disabled="saving || !ws.currentNote.value?.trim()" @click="finish">{{ saving ? '保存中…' : '完成笔记并返回' }}</button></footer></section></template>
<style scoped>.sfx-note-stage{padding:var(--space-6);display:grid;gap:var(--space-4);width:100%}.sfx-note-stage header,.sfx-note-stage footer{display:flex;gap:var(--space-3);align-items:center}.sfx-note-stage header h2{flex:1}.sfx-note-stage textarea{width:100%;resize:vertical;padding:var(--space-3)}</style>
