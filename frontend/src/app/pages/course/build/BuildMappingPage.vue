<script setup>
import { computed, onMounted, ref } from 'vue'
import { generateCoursePpt, getPptMappingState, updatePptMapping, uploadExistingPpt } from '@/api/course_editor.js'
import { useRoute } from 'vue-router'
import SfxButton from '@/app/ui/SfxButton.vue'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const state = ref(null)
const loading = ref(true)
const inputRef = ref(null)
const message = ref('')

async function load() {
  loading.value = true
  try { state.value = await getPptMappingState(courseId.value) } catch (error) { message.value = error?.message || '映射状态读取失败' } finally { loading.value = false }
}
async function onUpload(event) {
  const file = event.target.files?.[0]
  if (!file) return
  message.value = '正在上传并创建解析任务…'
  try { await uploadExistingPpt(courseId.value, file); message.value = '上传成功，解析任务已进入任务中心'; await load() } catch (error) { message.value = error?.message || '上传失败' }
  event.target.value = ''
}
async function onGenerate() {
  message.value = '正在请求 AI PPT 生成…'
  try { await generateCoursePpt(courseId.value); message.value = 'AI PPT 已生成并进入统一解析链'; await load() } catch (error) { message.value = error?.message || 'AI PPT 暂不可用' }
}
async function saveMapping(node) {
  try { await updatePptMapping(courseId.value, node.outline_node_id, { page_range: node.page_range, confidence: node.confidence }) } catch (error) { message.value = error?.message || '映射保存失败' }
}
onMounted(load)
</script>

<template>
  <section class="stage">
    <div v-if="loading" class="empty">正在读取映射状态…</div>
    <div v-else-if="!state?.has_ppt" class="frozen">
      <h2>当前课程尚无可映射的 PPT 文件</h2>
      <p>PDF、DOCX 和 DOC 的页码仍可用于原文引用，但不会自动成为教学 PPT 映射。</p>
      <input ref="inputRef" hidden type="file" accept=".ppt,.pptx" @change="onUpload" />
      <div class="actions"><SfxButton variant="primary" size="sm" @click="inputRef?.click()">上传现有 PPT</SfxButton><SfxButton variant="tertiary" size="sm" :disabled="!state?.actions?.generate_ai" @click="onGenerate">AI 智慧生成 PPT</SfxButton></div>
      <small>根据已经确认的课程结构和讲授脚本生成</small>
    </div>
    <div v-else class="ready">
      <h2>已发现 PPT 文件</h2><p>可编辑课程节点对应的幻灯片页码。</p>
      <div class="mapping-list"><label v-for="node in state.nodes" :key="node.outline_node_id"><span>{{ node.title }}</span><input v-model="node.page_range" placeholder="页码，例如 1-3" @blur="saveMapping(node)" /></label></div>
    </div>
    <p v-if="message" class="message">{{ message }}</p>
  </section>
</template>

<style scoped>
.stage{padding:0;height:100%;overflow-y:auto}
.frozen,.ready{border:1px dashed var(--border-strong);border-radius:var(--radius-lg);padding:var(--space-8) var(--space-6);text-align:center;background:var(--surface-cool);color:var(--text-secondary)}
.frozen h2,.ready h2{color:var(--text-primary)}
.actions{display:flex;justify-content:center;gap:var(--space-2);margin:var(--space-6) 0 var(--space-2)}
.frozen small{color:var(--text-muted)}
.empty{text-align:center;padding:var(--space-12);color:var(--text-muted)}
.mapping-list{display:grid;gap:var(--space-2);text-align:left;margin:var(--space-6) auto;max-width:720px}
.mapping-list label{display:flex;align-items:center;gap:var(--space-3);padding:var(--space-2);background:var(--surface-panel);border:1px solid var(--border-default);border-radius:var(--radius-sm)}
.mapping-list span{flex:1}
.mapping-list input{width:150px;padding:var(--space-1);border:1px solid var(--border-strong);border-radius:var(--radius-sm)}
.message{margin-top:var(--space-4);color:var(--ink-700)}
</style>
