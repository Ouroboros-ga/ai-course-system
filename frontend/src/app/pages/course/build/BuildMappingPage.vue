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
    <p class="eyebrow">Step 7</p><h1>教学 PPT 映射</h1>
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
.stage{background:#fff;border:1px solid #dbe2ea;border-radius:12px;padding:24px;min-height:520px}h1{margin:4px 0 24px;font-size:24px}.eyebrow{color:#64748b;font-size:13px}.frozen,.ready{border:1px dashed #cbd5e1;border-radius:12px;padding:36px 24px;text-align:center;background:#f8fafc;color:#475569}.frozen h2,.ready h2{color:#334155}.actions{display:flex;justify-content:center;gap:10px;margin:24px 0 10px}.frozen small{color:#64748b}.empty{text-align:center;padding:56px;color:#64748b}.mapping-list{display:grid;gap:8px;text-align:left;margin:20px auto;max-width:720px}.mapping-list label{display:flex;align-items:center;gap:12px;padding:10px;background:#fff;border:1px solid #e2e8f0;border-radius:8px}.mapping-list span{flex:1}.mapping-list input{width:150px;padding:6px;border:1px solid #cbd5e1;border-radius:6px}.message{margin-top:16px;color:#1769aa}
</style>
