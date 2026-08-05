<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  generateCoursePpt,
  getPptMappingState,
  getPptMappingWorkspace,
  matchPptMapping,
  savePptMappings,
  uploadExistingPpt,
} from '@/api/course_editor.js'
import { useRoute } from 'vue-router'
import { Check, FileImage, Layers3, Sparkles, Wand2 } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'
import { apiErrorMessage } from '@/utils/apiErrorMessage.js'

const route = useRoute()
const courseId = computed(() => Number(route.params.courseId))
const workbench = inject('courseBuildWorkbench', null)

const state = ref(null)
const workspace = ref(null)
const loading = ref(true)
const workspaceLoading = ref(false)
const matching = ref(false)
const saving = ref(false)
const inputRef = ref(null)
const message = ref('')
const selectedMaterialVersionId = ref('')
const selectedNodeId = ref('')
const selectedPages = ref([])
const currentPage = ref(1)
const manualEdits = ref({})

const prepBatchRunning = computed(() => Boolean(workbench?.batchRun))
const hasCurrentPptVersions = computed(() => Boolean(state.value?.ppt_materials?.length))
const mappingContractReady = computed(() => state.value?.mapping_contract_version === 'ppt-mapping/v2')
const mappingNodes = computed(() => (state.value?.nodes || []).filter(node => node.node_type === 'knowledge_point'))
const selectedNode = computed(() => mappingNodes.value.find(node => node.outline_node_id === selectedNodeId.value) || null)
const selectedMaterial = computed(() => (
  state.value?.ppt_materials?.find(item => item.material_version_id === selectedMaterialVersionId.value) || null
))
const workspacePages = computed(() => workspace.value?.pages || [])
const currentWorkspacePage = computed(() => (
  workspacePages.value.find(page => page.page === currentPage.value) || workspacePages.value[0] || null
))
const selectedPageLabel = computed(() => selectedPages.value.length ? `第 ${selectedPages.value.join('、')} 页` : '尚未选择页面')
const pendingEditCount = computed(() => Object.keys(manualEdits.value).length)
const canMatchCurrentNode = computed(() => Boolean(selectedNode.value && selectedMaterial.value && !matching.value && !prepBatchRunning.value))
const canMatchSelectedPages = computed(() => Boolean(
  selectedMaterial.value && selectedPages.value.length && !matching.value && !prepBatchRunning.value,
))
const canOrganize = computed(() => (
  mappingContractReady.value && hasCurrentPptVersions.value && !matching.value && !prepBatchRunning.value
))

const FIRST_PREP_PHASES = new Set(['parsing_materials', 'assembling_corpus', 'submitting_build', 'building'])
const isFirstPrepInProgress = computed(() => FIRST_PREP_PHASES.has(workbench?.draftBuildPhase))

function mappingKey(nodeId = selectedNodeId.value, materialVersionId = selectedMaterialVersionId.value) {
  return `${nodeId}:${materialVersionId}`
}

function existingMapping(nodeId = selectedNodeId.value, materialVersionId = selectedMaterialVersionId.value) {
  const node = mappingNodes.value.find(item => item.outline_node_id === nodeId)
  return (node?.ppt_mappings || []).find(item => item.material_version_id === materialVersionId) || null
}

function resetSelectedPagesFromMapping() {
  const edit = manualEdits.value[mappingKey()]
  const mapping = existingMapping()
  selectedPages.value = [...(edit?.page_refs || mapping?.page_refs || [])]
  currentPage.value = selectedPages.value[0] || workspacePages.value[0]?.page || 1
}

function prepareState(data) {
  const materials = data.ppt_materials || []
  for (const node of data.nodes || []) {
    node.ppt_mappings = node.ppt_mappings || (node.ppt_mapping ? [node.ppt_mapping] : [])
  }
  state.value = data
  if (!materials.some(item => item.material_version_id === selectedMaterialVersionId.value)) {
    selectedMaterialVersionId.value = materials[0]?.material_version_id || ''
  }
  if (!mappingNodes.value.some(node => node.outline_node_id === selectedNodeId.value)) {
    selectedNodeId.value = mappingNodes.value[0]?.outline_node_id || ''
  }
}

async function load({ keepEdits = true } = {}) {
  loading.value = true
  try {
    prepareState(await getPptMappingState(courseId.value))
    if (!keepEdits) manualEdits.value = {}
    await loadWorkspace({ reset: true })
  } catch (error) {
    message.value = apiErrorMessage(error, '映射状态读取失败')
  } finally {
    loading.value = false
  }
}

async function loadWorkspace({ reset = false } = {}) {
  if (!selectedMaterialVersionId.value) {
    workspace.value = null
    return
  }
  workspaceLoading.value = true
  try {
    const pageStart = reset ? 1 : workspace.value?.next_page_start
    if (!pageStart) return
    const data = await getPptMappingWorkspace(courseId.value, selectedMaterialVersionId.value, {
      page_start: pageStart,
      page_size: 12,
    })
    workspace.value = reset
      ? data
      : { ...data, pages: [...(workspace.value?.pages || []), ...(data.pages || [])] }
    if (data.render_warning) {
      message.value = '教师原始 PPT 页图暂时不可用；可稍后重试，OCR 摘要仍可用于辅助匹配。'
    }
    if (reset) resetSelectedPagesFromMapping()
    if (!currentPage.value && workspace.value.pages?.length) currentPage.value = workspace.value.pages[0].page
  } catch (error) {
    message.value = apiErrorMessage(error, 'PPT 页图读取失败')
  } finally {
    workspaceLoading.value = false
  }
}

function authorizedImageUrl(url) {
  if (!url) return ''
  const token = localStorage.getItem('token')
  if (!token) return url
  return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
}

function selectNode(nodeId) {
  selectedNodeId.value = nodeId
  resetSelectedPagesFromMapping()
}

function selectMaterial(versionId) {
  if (selectedMaterialVersionId.value === versionId) return
  selectedMaterialVersionId.value = versionId
  currentPage.value = 1
  loadWorkspace({ reset: true })
}

function togglePage(page) {
  const current = new Set(selectedPages.value)
  if (current.has(page)) current.delete(page)
  else current.add(page)
  selectedPages.value = [...current].sort((left, right) => left - right)
  currentPage.value = page
  if (selectedNode.value && selectedMaterial.value && selectedPages.value.length) {
    const mapping = existingMapping()
    manualEdits.value = {
      ...manualEdits.value,
      [mappingKey()]: {
        outline_node_id: selectedNode.value.outline_node_id,
        material_version_id: selectedMaterial.value.material_version_id,
        page_refs: [...selectedPages.value],
        confidence: mapping?.confidence ?? 1,
        locked: true,
      },
    }
  } else {
    delete manualEdits.value[mappingKey()]
    manualEdits.value = { ...manualEdits.value }
  }
}

function clearSelectedPages() {
  selectedPages.value = []
  delete manualEdits.value[mappingKey()]
  manualEdits.value = { ...manualEdits.value }
}

async function saveManualMappings() {
  const mappings = Object.values(manualEdits.value)
  if (!mappings.length || saving.value) return
  saving.value = true
  message.value = ''
  try {
    const result = await savePptMappings(courseId.value, mappings)
    manualEdits.value = {}
    message.value = `已保存 ${result.saved_count || mappings.length} 条教师映射；后续一键匹配不会覆盖锁定项。`
    await load({ keepEdits: false })
  } catch (error) {
    message.value = apiErrorMessage(error, '映射保存失败')
  } finally {
    saving.value = false
  }
}

function startAgentMessage(reason) {
  const agentMessage = { role: 'agent', running: true, reason, changed: [] }
  if (workbench) {
    workbench.agentOpen = true
    workbench.batchRun = { action: 'ppt_mapping_match', startedAt: Date.now() }
    workbench.agentMessages.push(agentMessage)
  }
  return agentMessage
}

async function runMatch(mode) {
  if (matching.value || prepBatchRunning.value) return
  if (!state.value?.has_ppt || !mappingContractReady.value || !hasCurrentPptVersions.value) {
    reportUnavailable('PPT 材料尚未形成可编辑版本，请等待解析完成后再匹配。')
    return
  }
  if (mode === 'node' && !selectedNode.value) {
    reportUnavailable('请先从目录选择一个知识点。')
    return
  }
  if (mode === 'selected_pages' && !selectedPages.value.length) {
    reportUnavailable('请先在 PPT 页图中选择至少一页。')
    return
  }
  const labels = {
    all_unlocked: '正在匹配全部未锁定知识点与当前 PPT 页图 OCR，请勿进行其他智能优化。',
    node: `正在重新匹配“${selectedNode.value?.display_label || selectedNode.value?.title}”。`,
    selected_pages: `正在为所选 ${selectedPageLabel.value} 查找最合适的知识点。`,
  }
  const agentMessage = startAgentMessage(labels[mode])
  matching.value = true
  message.value = ''
  try {
    const payload = {
      mode,
      ...(mode !== 'all_unlocked' ? { material_version_id: selectedMaterialVersionId.value } : {}),
      ...(mode === 'node' ? { outline_node_id: selectedNodeId.value } : {}),
      ...(mode === 'selected_pages' ? { page_refs: selectedPages.value } : {}),
    }
    const result = await matchPptMapping(courseId.value, payload)
    const noReliableMatch = result.outcome === 'no_reliable_match'
    message.value = noReliableMatch
      ? '未找到可信候选页，可直接在页图中选择，或对当前知识点重新匹配。'
      : `匹配完成：已更新 ${result.updated_count || 0} 条未锁定映射。`
    Object.assign(agentMessage, {
      running: false,
      error: false,
      reason: message.value,
      changed: noReliableMatch ? [] : [`已更新 ${result.updated_count || 0} 条映射`],
    })
    await load({ keepEdits: true })
  } catch (error) {
    message.value = apiErrorMessage(error, 'PPT 映射匹配失败')
    Object.assign(agentMessage, { running: false, error: true, reason: message.value })
  } finally {
    if (workbench) workbench.batchRun = null
    matching.value = false
  }
}

function reportUnavailable(reason) {
  message.value = reason
  if (!workbench) return
  workbench.agentOpen = true
  workbench.agentMessages.push({ role: 'agent', error: true, reason })
}

async function onUpload(event) {
  const file = event.target.files?.[0]
  if (!file) return
  message.value = '正在上传并创建解析任务…'
  try {
    const uploaded = await uploadExistingPpt(courseId.value, file)
    message.value = uploaded?.deduplicated
      ? '相同 PPT 已在本课程中，已保留已有解析结果。'
      : '上传成功，PPT 解析完成后将显示逐页图片。'
    await load({ keepEdits: false })
  } catch (error) {
    message.value = apiErrorMessage(error, '上传失败')
  }
  event.target.value = ''
}

async function onGenerate() {
  message.value = '正在请求 AI PPT 生成…'
  try {
    await generateCoursePpt(courseId.value)
    message.value = 'AI PPT 已生成并进入统一解析链路。'
    await load({ keepEdits: false })
  } catch (error) {
    message.value = apiErrorMessage(error, 'AI PPT 暂不可用')
  }
}

watch([canOrganize, matching, prepBatchRunning], () => {
  if (!workbench) return
  workbench.stageActions = {
    canOrganize: canOrganize.value,
    organizing: matching.value,
    onOrganize: () => runMatch('all_unlocked'),
    organizeLabel: '一键初配全部',
  }
}, { immediate: true })

watch([selectedNodeId, selectedMaterialVersionId], () => {
  if (!loading.value && selectedNodeId.value && selectedMaterialVersionId.value) resetSelectedPagesFromMapping()
})

onMounted(() => load({ keepEdits: false }))
onBeforeUnmount(() => { if (workbench) workbench.stageActions = null })
</script>

<template>
  <section class="stage">
    <div v-if="loading" class="empty">正在读取 PPT 映射工作区…</div>

    <div v-else-if="isFirstPrepInProgress && !state?.has_ppt" class="first-prep-pending" role="status">
      <div class="first-prep-icon" aria-hidden="true"><Sparkles :size="26" /></div>
      <h3>助教智能体首次备课中</h3>
      <p>课程结构和材料解析完成后，即可基于每页 PPT 图像和 OCR 文本进行映射。</p>
    </div>

    <div v-else-if="!state?.has_ppt" class="frozen">
      <h2>当前课程尚无可映射的 PPT 文件</h2>
      <p>上传后将生成按材料版本区分的 PPT 页图；相同页码不会跨文件混用。</p>
      <input ref="inputRef" hidden type="file" accept=".ppt,.pptx" @change="onUpload" />
      <div class="actions">
        <SfxButton variant="primary" size="sm" @click="inputRef?.click()">上传现有 PPT</SfxButton>
        <SfxButton variant="tertiary" size="sm" :disabled="!state?.actions?.generate_ai" @click="onGenerate">AI 生成 PPT</SfxButton>
      </div>
    </div>

    <template v-else>
      <div class="deck-tabs" role="tablist" aria-label="PPT 文件">
        <SfxButton
          v-for="material in state.ppt_materials"
          :key="material.material_version_id"
          class="deck-tab"
          size="sm"
          :variant="material.material_version_id === selectedMaterialVersionId ? 'primary' : 'tertiary'"
          :aria-selected="material.material_version_id === selectedMaterialVersionId"
          @click="selectMaterial(material.material_version_id)"
        >
          <FileImage :size="14" /> <span>{{ material.name }}</span><small>{{ material.page_count || '解析中' }} 页</small>
        </SfxButton>
      </div>

      <div class="mapping-workbench">
        <aside class="node-rail" aria-label="知识点目录">
          <div class="rail-heading"><span>知识点目录</span><small>{{ mappingNodes.length }} 个</small></div>
          <div class="node-list">
            <SfxButton
              v-for="node in mappingNodes"
              :key="node.outline_node_id"
              class="node-item"
              size="sm"
              :variant="node.outline_node_id === selectedNodeId ? 'primary' : 'tertiary'"
              :aria-pressed="node.outline_node_id === selectedNodeId"
              @click="selectNode(node.outline_node_id)"
            >
              <span>{{ node.display_label || node.title }}</span>
              <small v-if="existingMapping(node.outline_node_id, selectedMaterialVersionId)?.page_refs?.length">
                {{ existingMapping(node.outline_node_id, selectedMaterialVersionId).page_range }}
              </small>
            </SfxButton>
          </div>
        </aside>

        <main class="ppt-canvas">
          <div class="selection-summary">
            <div>
              <span>当前知识点</span>
              <strong>{{ selectedNode?.display_label || selectedNode?.title || '请选择知识点' }}</strong>
            </div>
            <div>
              <span>已选页面</span>
              <strong>{{ selectedPageLabel }}</strong>
            </div>
            <div class="selection-actions">
              <SfxButton variant="tertiary" size="sm" :disabled="!canMatchCurrentNode" @click="runMatch('node')">
                <Wand2 :size="14" /> 匹配当前知识点
              </SfxButton>
              <SfxButton variant="tertiary" size="sm" :disabled="!canMatchSelectedPages" @click="runMatch('selected_pages')">
                <Layers3 :size="14" /> 为所选页找节点
              </SfxButton>
              <SfxButton variant="tertiary" size="sm" :disabled="!selectedPages.length" @click="clearSelectedPages">清除选择</SfxButton>
            </div>
          </div>

          <div v-if="workspaceLoading && !workspacePages.length" class="canvas-empty">正在加载 PPT 页图…</div>
          <div v-else-if="!workspacePages.length" class="canvas-empty">
            <FileImage :size="28" />
            <span>该 PPT 尚无可显示的页图；材料解析完成后会自动出现。</span>
          </div>
          <template v-else>
            <section class="page-preview">
              <img
                v-if="currentWorkspacePage?.image_url"
                :src="authorizedImageUrl(currentWorkspacePage.image_url)"
                :alt="`PPT 第 ${currentWorkspacePage.page} 页`"
              />
              <div v-else class="render-pending">
                <FileImage :size="34" />
                <strong>第 {{ currentWorkspacePage?.page }} 页图正在生成</strong>
                <p>正在生成教师上传原课件的真实幻灯片；OCR 只保留为下方摘要。</p>
              </div>
              <span v-if="currentWorkspacePage?.image_source === 'teacher_original_ppt'" class="source-badge">
                教师原始 PPT 幻灯片
              </span>
            </section>

            <section class="ocr-panel">
              <strong>当前页 OCR 摘要</strong>
              <p>{{ currentWorkspacePage?.ocr_preview || '该页尚无可用 OCR 文本。' }}</p>
            </section>

            <section class="thumbnails" aria-label="PPT 页面选择">
              <SfxButton
                v-for="page in workspacePages"
                :key="page.page"
                class="thumbnail"
                size="sm"
                :variant="selectedPages.includes(page.page) ? 'primary' : 'tertiary'"
                :aria-pressed="selectedPages.includes(page.page)"
                @click="togglePage(page.page)"
              >
                <span>第 {{ page.page }} 页</span>
                <small>{{ page.ocr_available ? 'OCR 就绪' : '无 OCR' }}</small>
                <Check v-if="selectedPages.includes(page.page)" :size="14" />
              </SfxButton>
            </section>
            <SfxButton
              v-if="workspace?.next_page_start"
              variant="tertiary"
              size="sm"
              :disabled="workspaceLoading"
              @click="loadWorkspace()"
            >加载更多页面</SfxButton>
          </template>
        </main>
      </div>

      <footer class="save-bar">
        <div>
          <strong>{{ pendingEditCount ? `待保存 ${pendingEditCount} 条映射` : '尚无待保存的手工修改' }}</strong>
          <p v-if="message" class="message" role="status">{{ message }}</p>
        </div>
        <SfxButton variant="primary" size="sm" :disabled="!pendingEditCount || saving || matching" @click="saveManualMappings">
          <Check :size="14" /> {{ saving ? '正在保存…' : '保存映射' }}
        </SfxButton>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.stage{height:100%;min-height:0;overflow:hidden;display:flex;flex-direction:column;gap:var(--space-4);padding:0}
.empty,.canvas-empty{display:grid;place-items:center;min-height:220px;color:var(--text-muted);text-align:center}
.frozen{margin:auto;border:1px dashed var(--border-strong);border-radius:var(--radius-lg);padding:var(--space-8) var(--space-6);text-align:center;background:var(--surface-cool);color:var(--text-secondary)}
.frozen h2{margin-top:0;color:var(--text-primary)}
.actions,.deck-tabs{display:flex;flex-wrap:wrap;gap:var(--space-2)}
.actions{justify-content:center;margin-top:var(--space-5)}
.deck-tabs{flex-shrink:0}.deck-tab{max-width:220px;display:grid!important;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:0 var(--space-2);text-align:left;line-height:1.3}.deck-tab svg{grid-row:1/3;align-self:center}.deck-tab>span{grid-column:2;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--ui-sm-size)}.deck-tab small{grid-column:2;display:block;opacity:.78;font-size:11px}
.mapping-workbench{display:grid;grid-template-columns:260px minmax(0,1fr);grid-template-rows:minmax(0,1fr);flex:1;min-height:0;border:1px solid var(--border-default);border-radius:var(--radius-md);overflow:hidden;background:var(--surface-canvas)}
.node-rail{display:flex;flex-direction:column;min-height:0;border-right:1px solid var(--border-default);background:var(--surface-panel)}
.rail-heading{display:flex;justify-content:space-between;align-items:center;padding:var(--space-3);border-bottom:1px solid var(--border-subtle);font-size:var(--ui-md-size);font-weight:var(--ui-md-weight);color:var(--text-primary)}
.rail-heading small{color:var(--text-muted);font-size:var(--caption-size)}
.node-list{display:grid;align-content:start;gap:var(--space-1);overflow-y:auto;min-height:0;padding:var(--space-2)}
.node-item{justify-content:space-between;width:100%;min-height:40px;text-align:left}.node-item>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.node-item small{margin-left:var(--space-2);white-space:nowrap;opacity:.8}
.ppt-canvas{display:flex;flex-direction:column;gap:var(--space-3);min-width:0;min-height:0;overflow-y:auto;padding:var(--space-3)}
.selection-summary{display:flex;align-items:center;gap:var(--space-4);padding:var(--space-3);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);background:var(--surface-panel)}
.selection-summary>div:not(.selection-actions){display:grid;gap:2px;min-width:0;flex:1}.selection-summary span{font-size:var(--caption-size);color:var(--text-muted)}.selection-summary strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--ui-md-size);color:var(--text-primary)}
.selection-actions{display:flex;gap:var(--space-2);flex-shrink:0}
.page-preview{position:relative;display:flex;align-items:center;justify-content:center;flex:0 0 clamp(320px,50vh,560px);min-height:320px;max-height:560px;padding:var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-sm);background:#202938}.page-preview img{display:block;max-width:100%;max-height:560px;object-fit:contain;box-shadow:0 8px 24px rgba(16,26,49,.28)}.source-badge{position:absolute;top:var(--space-3);left:var(--space-3);padding:2px var(--space-2);border:1px solid var(--border-default);border-radius:var(--radius-sm);background:var(--surface-panel);color:var(--text-secondary);font-size:var(--caption-size)}
.render-pending{display:grid;justify-items:center;gap:var(--space-2);max-width:360px;color:var(--text-inverse);text-align:center}.render-pending p{margin:0;color:#d6dde6;font-size:var(--ui-sm-size);line-height:1.5}
.ocr-panel{display:flex;flex-direction:column;flex:0 0 132px;min-height:132px;max-height:132px;box-sizing:border-box;overflow-y:auto;padding:var(--space-3);border-left:3px solid var(--ink-500);background:var(--surface-cool);color:var(--text-secondary)}.ocr-panel strong{flex:0 0 auto;font-size:var(--ui-sm-size);color:var(--text-primary)}.ocr-panel p{margin:var(--space-1) 0 0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:var(--caption-size);line-height:1.5}
.thumbnails{display:grid;grid-template-columns:repeat(auto-fill,minmax(116px,1fr));gap:var(--space-2)}.thumbnail{position:relative;display:grid!important;justify-items:start;gap:2px;min-height:54px;text-align:left}.thumbnail small{opacity:.76}.thumbnail svg{position:absolute;right:var(--space-2);top:50%;transform:translateY(-50%)}
.save-bar{display:flex;align-items:center;justify-content:space-between;gap:var(--space-4);flex-shrink:0;padding:var(--space-2) var(--space-3);border:1px solid var(--border-strong);border-radius:var(--radius-md);background:var(--surface-panel)}.save-bar>div{display:grid;gap:1px;min-width:0}.save-bar strong{font-size:var(--ui-md-size);color:var(--text-primary)}
.message{margin:0;color:var(--ink-700);font-size:var(--caption-size);line-height:1.4;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.first-prep-pending{display:grid;justify-items:center;gap:var(--space-3);margin:auto;text-align:center;color:var(--text-secondary)}.first-prep-pending h3{margin:0;color:var(--text-primary)}.first-prep-pending p{max-width:440px;margin:0}.first-prep-icon{display:flex;align-items:center;justify-content:center;width:56px;height:56px;border-radius:var(--radius-full);background:var(--ink-100);color:var(--ink-700)}
@media (max-width:1100px){.mapping-workbench{grid-template-columns:220px minmax(0,1fr)}}
</style>
