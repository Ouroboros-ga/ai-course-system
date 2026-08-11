<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Captions, Check, CircleAlert, FileImage, RefreshCw, Send, Sparkles, Volume2 } from 'lucide-vue-next'
import { getTeachingScripts } from '@/api/course_editor.js'
import {
  activateMediaRelease,
  buildAvatarCues,
  buildPptManifest,
  createMediaGenerationJob,
  createMediaRelease,
  executeMediaTtsJob,
  getMediaProviderHealth,
  getPlatformMediaPresets,
  planMediaBatch,
  confirmMediaBatch,
  getMediaBatch,
  previewMediaReleaseItem,
  previewMediaReleaseItemPlayback,
  freezeAudioPlaylist,
  getMediaRelease,
  listMediaGenerationJobs,
  listMediaReleases,
  retryMediaGenerationJob,
} from '@/api/media_release.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'
import { apiErrorMessage } from '@/utils/apiErrorMessage.js'
import { withAccessToken } from '@/features/student-learning/adapters/playerWorkspaceAdapter.js'

const route = useRoute()
const router = useRouter()
const courseId = computed(() => Number(route.params.courseId))
const workbench = inject('courseBuildWorkbench', null)
const courseContext = inject('courseContext', null)

const state = ref('loading')
const error = ref('')
const providerError = ref('')
const notice = ref('')
const scripts = ref([])
const jobs = ref([])
const releases = ref([])
const releaseDetail = ref(null)
const providerHealth = ref(null)
const presetCatalog = ref({ voices: [], avatars: [] })
const selectedVoicePresetId = ref('')
const selectedVoicePresetVersion = ref('')
const selectedAvatarPresetId = ref('')
const selectedAvatarPresetVersion = ref('')
const selectedScriptId = ref('')
const selectedReleaseId = ref('')
const paidTtsConfirmed = ref(false)
const acting = ref('')
const refreshing = ref(false)
const batchNodeIds = ref([])
const batchPlan = ref(null)
const batchState = ref(null)
const previewItem = ref(null)
const previewPlayback = ref(null)
const previewAudio = ref(null)
const previewPanel = ref(null)
const previewNodeLabel = ref('')
const lastAutoPreviewId = ref('')

const allowed = computed(() => courseContext?.allowed?.value ?? {})
const canGenerate = computed(() => Boolean(allowed.value['course.media.generate']))
const canPublish = computed(() => Boolean(allowed.value['course.publish']))
const selectedScript = computed(() => scripts.value.find((item) => item.script_node_id === selectedScriptId.value) ?? null)
const selectedNodeDbId = computed(() => Number(selectedScript.value?.script_node_db_id) || null)
const workingRelease = computed(() => releaseDetail.value ?? releases.value.find((item) => item.release_id === selectedReleaseId.value) ?? null)
const provider = computed(() => providerHealth.value?.tts ?? null)
const providerKey = computed(() => provider.value?.provider_key || '')
const providerDisplayName = computed(() => provider.value?.effective_provider || '未配置')
const providerReady = computed(() => provider.value?.status === 'ready' && Boolean(providerKey.value))
const providerNeedsConfirmation = computed(() => Boolean(provider.value?.requires_confirmation))
const providerIsDemo = computed(() => Boolean(provider.value?.demo_mode))
const selectedVoicePreset = computed(() => presetCatalog.value.voices.find(item => item.preset_id === selectedVoicePresetId.value && item.version === selectedVoicePresetVersion.value) ?? null)
const selectedAvatarPreset = computed(() => presetCatalog.value.avatars.find(item => item.preset_id === selectedAvatarPresetId.value && item.version === selectedAvatarPresetVersion.value) ?? null)
const selectedCharCount = computed(() => Array.from(selectedScript.value?.content || '').length)
const selectedByteCount = computed(() => new TextEncoder().encode(selectedScript.value?.content || '').length)

const releaseTtsJobs = computed(() => jobs.value.filter((job) => (
  job.job_type === 'tts' && job.media_release_id === workingRelease.value?.release_id
)))
const releaseTtsJob = computed(() => releaseTtsJobs.value[0] ?? null)
const selectedTtsJob = computed(() => releaseTtsJobs.value.find((job) => job.node_id === selectedNodeDbId.value) ?? null)
// A playlist release intentionally owns many knowledge-point jobs. Treating
// its first TTS job as a single-node binding hides the PPT/playlist/activation
// controls whenever another rail item is selected. Only legacy single-node
// releases have a selected-node binding.
const releaseBoundNodeId = computed(() => (
  workingRelease.value?.release_metadata?.audio_playlist_mode
    ? null
    : releaseTtsJob.value?.node_id ?? workingRelease.value?.cues?.[0]?.node_id ?? null
))
const releaseMatchesSelection = computed(() => !releaseBoundNodeId.value || releaseBoundNodeId.value === selectedNodeDbId.value)
const boundScript = computed(() => scripts.value.find((item) => item.script_node_db_id === releaseBoundNodeId.value) ?? null)
const cueJob = computed(() => jobs.value.find((job) => (
  job.job_type === 'timeline_publish' && job.media_release_id === workingRelease.value?.release_id
)) ?? null)
const hasFrozenCues = computed(() => Boolean(
  workingRelease.value?.avatar_cues_object_key && workingRelease.value?.subtitle_manifest_object_key,
))
const hasPptManifest = computed(() => Boolean(workingRelease.value?.ppt_manifest_object_key))
const isPlaylistRelease = computed(() => Boolean(workingRelease.value?.release_metadata?.audio_playlist_mode))
const hasFrozenPlaylist = computed(() => Boolean(workingRelease.value?.audio_playlist_object_key && workingRelease.value?.audio_playlist_sha256))
const canActivateWorkingRelease = computed(() => {
  if (!workingRelease.value || workingRelease.value.status !== 'draft') return false
  return isPlaylistRelease.value
    ? hasFrozenPlaylist.value
    : hasFrozenCues.value
})
const hasPendingJobs = computed(() => jobs.value.some((job) => ['pending', 'running'].includes(job.status)))
const activeBatchId = computed(() => batchState.value?.batch_id || workingRelease.value?.release_metadata?.media_build_batch_id || '')
const batchItems = computed(() => batchState.value?.items ?? workingRelease.value?.items ?? [])
const canCreateDraft = computed(() => Boolean(canGenerate.value && selectedNodeDbId.value && selectedScript.value?.content?.trim()))
const canSubmitTts = computed(() => Boolean(
  canCreateDraft.value
  && workingRelease.value?.status === 'draft'
  && releaseMatchesSelection.value
  && providerReady.value
  && (!providerNeedsConfirmation.value || paidTtsConfirmed.value)
  && !['pending', 'running'].includes(selectedTtsJob.value?.status),
))
const batchSelectedScripts = computed(() => scripts.value.filter(item => batchNodeIds.value.includes(Number(item.script_node_db_id))))
// 左侧 rail 当前选中的知识点在批量媒体结果里对应的 item；有 audio_object_key 才能自动试听。
const selectedBatchItem = computed(() => findBatchItemForScript(selectedScript.value))
const canPlanBatch = computed(() => canGenerate.value && batchSelectedScripts.value.length > 0 && batchSelectedScripts.value.length <= 20)
const batchPlanMatchesSelections = computed(() => Boolean(
  batchPlan.value
  && batchPlan.value.voice_preset?.preset_id === selectedVoicePresetId.value
  && batchPlan.value.voice_preset?.version === selectedVoicePresetVersion.value
  && batchPlan.value.avatar_preset?.preset_id === selectedAvatarPresetId.value
  && batchPlan.value.avatar_preset?.version === selectedAvatarPresetVersion.value
))
const canConfirmBatch = computed(() => canPlanBatch.value && Boolean(batchPlan.value?.can_confirm)
  && batchPlanMatchesSelections.value
  && (!providerNeedsConfirmation.value || paidTtsConfirmed.value))
// Playlist (batch) releases freeze Cue assets per MediaReleaseItem, not on the
// release row.  ``hasFrozenCues`` therefore stays false for the whole batch
// while every item is already ``ready``.  Gate the PPT manifest step on the
// batch-level readiness instead of the single-node release fields.
const batchReady = computed(() => {
  const items = batchItems.value
  if (!items.length) return false
  return batchState.value?.status === 'ready' || items.every((item) => item.status === 'ready')
})
const releaseCueAssetsReady = computed(() => (
  isPlaylistRelease.value ? batchReady.value : hasFrozenCues.value
))
const batchAudioReady = computed(() => {
  const items = batchItems.value
  return items.length > 0 && items.every((item) => Boolean(item.audio_object_key))
})
const coursePublished = computed(() => courseContext?.course?.value?.status === 'published')
const canBuildPptManifest = computed(() => isPlaylistRelease.value ? batchReady.value : hasFrozenCues.value)
const releaseActive = computed(() => workingRelease.value?.status === 'active')
const batchSteps = computed(() => {
  const audioDone = batchAudioReady.value
  const cueDone = batchReady.value
  const pptDone = hasPptManifest.value
  const playlistDone = hasFrozenPlaylist.value
  const activeDone = releaseActive.value
  const publishDone = coursePublished.value && activeDone
  const started = batchItems.value.length > 0
  return [
    { key: '01', label: 'Fake WAV', done: audioDone, active: started && !audioDone },
    { key: '02', label: 'Cue 冻结', done: cueDone, active: audioDone && !cueDone },
    { key: '03', label: 'PPT manifest', done: pptDone, active: cueDone && !pptDone },
    { key: '04', label: 'audio-playlist/v1', done: playlistDone, active: pptDone && !playlistDone },
    { key: '05', label: '激活', done: activeDone, active: playlistDone && !activeDone },
    { key: '06', label: '正式发布', done: publishDone, active: activeDone && !publishDone },
  ]
})

function jobTone(job) {
  if (job?.status === 'succeeded') return 'green'
  if (job?.status === 'failed' || job?.status === 'cancelled') return 'red'
  if (job?.status === 'running') return 'ink'
  if (job?.status === 'degraded' || job?.status === 'partial_success') return 'amber'
  return 'amber'
}

function releaseTone(release) {
  if (release?.status === 'active') return 'green'
  if (release?.status === 'draft') return 'amber'
  if (release?.status === 'withdrawn' || release?.status === 'stale') return 'red'
  return 'neutral'
}

function releaseStatusLabel(release) {
  return ({ draft: '草稿', active: '已激活', superseded: '已替换', withdrawn: '已撤回', stale: '资产失效' })[release?.status] || release?.status || '未知状态'
}

function jobStatusLabel(job) {
  return ({ pending: '等待处理', running: '处理中', succeeded: '已完成', failed: '失败', cancelled: '已取消', partial_success: '部分完成', degraded: '降级完成' })[job?.status] || job?.status || '未知状态'
}

function batchStatusLabel(status) {
  return ({ planned: '已计划', confirmed: '已确认', running: '处理中', ready: '全部就绪', failed: '失败', cancelled: '已取消' })[status] || status || '—'
}

function batchItemStatusLabel(status) {
  return ({ pending: '等待生成', tts_succeeded: '音频已生成', cached: '复用缓存', ready: '就绪（含字幕/Cue）', failed: '失败', blocked: '被阻塞' })[status] || status || '未知状态'
}

function scriptLabel(script) {
  return script?.display_label || script?.outline_title || script?.script_node_id || '未关联知识点'
}

// MediaReleaseItem keeps the script node DB id from the generation run.  A
// subsequent script edit can create a new TeachingScriptNode row while the
// knowledge point keeps its stable outline_node_id.  Match the durable id
// first, then fall back to that stable knowledge-point identity so an already
// ready audio item remains discoverable after a draft refresh.
function sameMediaNode(item, script) {
  if (!item || !script) return false
  const itemNodeId = Number(item.node_id)
  const scriptNodeId = Number(script.script_node_db_id)
  if (itemNodeId > 0 && scriptNodeId > 0 && itemNodeId === scriptNodeId) return true
  return Boolean(item.outline_node_id && script.outline_node_id
    && String(item.outline_node_id) === String(script.outline_node_id))
}

function findBatchItemForScript(script) {
  return batchItems.value.find((item) => sameMediaNode(item, script)) ?? null
}

function findScriptForBatchItem(item) {
  return scripts.value.find((script) => sameMediaNode(item, script)) ?? null
}

function jobLabel(job) {
  if (job?.job_type === 'tts') return '讲稿语音合成'
  if (job?.job_type === 'timeline_publish') return '字幕与数字人时间轴'
  return job?.job_type || '媒体任务'
}

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? '—' : date.toLocaleString('zh-CN', { hour12: false })
}

function makeTtsIdempotencyKey() {
  const revision = String(selectedScript.value?.updated_at || selectedCharCount.value)
    .replace(/[^a-zA-Z0-9]/g, '')
    .slice(-24)
  return `tts-${workingRelease.value.release_id}-${selectedNodeDbId.value}-${revision || 'initial'}`
}

function makeCueIdempotencyKey() {
  return `cue:${workingRelease.value.release_id}:${selectedTtsJob.value.job_id}`
}

function chooseDefaultRelease(nextReleases) {
  if (nextReleases.some((item) => item.release_id === selectedReleaseId.value)) return selectedReleaseId.value
  return nextReleases.find((item) => item.status === 'draft')?.release_id || nextReleases[0]?.release_id || ''
}

async function refreshReleaseDetail(releaseId = selectedReleaseId.value) {
  if (!releaseId) {
    releaseDetail.value = null
    return
  }
  releaseDetail.value = await getMediaRelease(courseId.value, releaseId)
}

async function refreshBatchState(batchId = activeBatchId.value) {
  if (!batchId) return null
  batchState.value = await getMediaBatch(courseId.value, batchId)
  return batchState.value
}

async function load({ quiet = false } = {}) {
  if (acting.value || refreshing.value) return
  if (!quiet) state.value = state.value === 'ready' ? 'refreshing' : 'loading'
  refreshing.value = true
  error.value = ''
  providerError.value = ''
  try {
    const [scriptData, jobData, releaseData, healthResult, presetResult] = await Promise.all([
      getTeachingScripts(courseId.value),
      listMediaGenerationJobs(courseId.value),
      listMediaReleases(courseId.value),
      getMediaProviderHealth().catch((caught) => ({ __error: caught })),
      getPlatformMediaPresets(courseId.value).catch((caught) => ({ __error: caught })),
    ])
    scripts.value = (scriptData?.items ?? []).filter((item) => (
      Number(item.script_node_db_id) > 0 && Boolean(item.content?.trim())
    ))
    jobs.value = jobData?.items ?? []
    releases.value = releaseData?.items ?? []
    providerHealth.value = healthResult?.__error ? null : healthResult
    if (!presetResult?.__error) {
      presetCatalog.value = { voices: presetResult.voices ?? [], avatars: presetResult.avatars ?? [] }
      if (!selectedVoicePresetId.value || !presetCatalog.value.voices.some(item => item.preset_id === selectedVoicePresetId.value && item.version === selectedVoicePresetVersion.value)) {
        const voice = presetCatalog.value.voices[0]
        selectedVoicePresetId.value = voice?.preset_id || ''
        selectedVoicePresetVersion.value = voice?.version || ''
      }
      if (!selectedAvatarPresetId.value || !presetCatalog.value.avatars.some(item => item.preset_id === selectedAvatarPresetId.value && item.version === selectedAvatarPresetVersion.value)) {
        const avatar = presetCatalog.value.avatars.find(item => item.preset_id === 'platform-female-instructor-v1') || presetCatalog.value.avatars[0]
        selectedAvatarPresetId.value = avatar?.preset_id || ''
        selectedAvatarPresetVersion.value = avatar?.version || ''
      }
    }
    providerError.value = healthResult?.__error
      ? apiErrorMessage(healthResult.__error, '无法确认语音服务状态，已阻止提交合成。')
      : ''
    if (!scripts.value.some((item) => item.script_node_id === selectedScriptId.value)) {
      selectedScriptId.value = scripts.value[0]?.script_node_id || ''
    }
    if (!batchNodeIds.value.length) batchNodeIds.value = scripts.value.slice(0, 20).map(item => Number(item.script_node_db_id))
    selectedReleaseId.value = chooseDefaultRelease(releases.value)
    await refreshReleaseDetail()
    await refreshBatchState()
    state.value = 'ready'
  } catch (caught) {
    error.value = apiErrorMessage(caught, '媒体创建中心暂时无法读取课程数据。')
    state.value = 'error'
  } finally {
    refreshing.value = false
  }
}

function toggleBatchNode(script) {
  const id = Number(script?.script_node_db_id)
  if (!id) return
  batchNodeIds.value = batchNodeIds.value.includes(id)
    ? batchNodeIds.value.filter(item => item !== id)
    : [...batchNodeIds.value, id].slice(0, 20)
}

// 返回某知识点在批量结果中可试听的 item（无音频时为 null）。试听入口统一在左侧列表。
function scriptItemAudio(script) {
  return findBatchItemForScript(script)
}

function withPreviewAccessToken(url) {
  const token = typeof window !== 'undefined' ? window.localStorage.getItem('token') : ''
  // Local object storage is served by the application, whose native audio
  // request cannot carry Axios' Authorization header.  Remote presigned URLs
  // must remain byte-for-byte intact.
  return String(url || '').startsWith('/') ? withAccessToken(url, token) : url
}

async function createBatchPlan() {
  if (!canPlanBatch.value || acting.value) return
  acting.value = 'batch-plan'; error.value = ''; notice.value = ''
  try {
    batchPlan.value = await planMediaBatch(courseId.value, { node_ids: batchNodeIds.value, provider_key: providerKey.value, provider_version: provider.value?.provider_version || '', voice_id: 'default', voice_preset_id: selectedVoicePresetId.value, voice_preset_version: selectedVoicePresetVersion.value, avatar_preset_id: selectedAvatarPresetId.value, avatar_preset_version: selectedAvatarPresetVersion.value })
    notice.value = `已核算 ${batchPlan.value.node_count} 个知识点：${batchPlan.value.billable_chars} 个待计费字符，${batchPlan.value.cache_hit_count} 个缓存命中。`
  } catch (caught) { error.value = apiErrorMessage(caught, '批量计划生成失败。') } finally { acting.value = '' }
}

async function confirmBatch() {
  if (!canConfirmBatch.value || acting.value) return
  acting.value = 'batch-confirm'; error.value = ''; notice.value = ''
  try {
    const response = await confirmMediaBatch(courseId.value, { node_ids: batchNodeIds.value, provider_key: providerKey.value, provider_version: provider.value?.provider_version || '', voice_id: 'default', voice_preset_id: selectedVoicePresetId.value, voice_preset_version: selectedVoicePresetVersion.value, avatar_preset_id: selectedAvatarPresetId.value, avatar_preset_version: selectedAvatarPresetVersion.value, idempotency_key: `batch-${courseId.value}-${Date.now()}`, label: '批量媒体建设草稿', paid_tts_confirmed: paidTtsConfirmed.value })
    batchState.value = response
    selectedReleaseId.value = response.release_id
    await load({ quiet: true })
    await refreshReleaseDetail(response.release_id)
    await refreshBatchState(response.batch_id)
    notice.value = '批量媒体任务已确认并提交；不会在页面轮询中重复调用付费 Provider。'
  } catch (caught) { error.value = apiErrorMessage(caught, '批量媒体确认失败。') } finally { acting.value = '' }
}

function applyPreview(audioPreview, playbackPreview, item) {
  previewItem.value = {
    ...audioPreview,
    audio_url: withPreviewAccessToken(audioPreview?.audio_url),
  }
  previewPlayback.value = playbackPreview
  const script = findScriptForBatchItem(item)
  previewNodeLabel.value = script ? scriptLabel(script) : `知识点 ${item?.node_id ?? ''}`
}

async function fetchPreview(item) {
  // The first request also repairs the guarded MediaAsset ledger for
  // legacy local drafts.  Keep the follow-up player projection sequential
  // so two browser requests never race to create the same immutable record.
  // Batch items belong to the batch's own release; workingRelease may have
  // been switched to a different draft, so never use it as the pairing key.
  const releaseId = batchState.value?.release_id || workingRelease.value?.release_id
  if (!releaseId) throw new Error('media_release_missing')
  const audioPreview = await previewMediaReleaseItem(
    courseId.value, releaseId, item.item_id,
  )
  const playbackPreview = await previewMediaReleaseItemPlayback(
    courseId.value, releaseId, item.item_id,
  )
  return { audioPreview, playbackPreview }
}

async function previewBatchItem(item) {
  if (!item?.item_id || acting.value) return
  acting.value = `preview-${item.item_id}`
  error.value = ''
  notice.value = ''
  try {
    // 先同步左侧选择，让“左侧选谁 = 试听谁”成立，不再出现选 A 显 B 的错位。
    const script = findScriptForBatchItem(item)
    if (script) selectedScriptId.value = script.script_node_id
    const { audioPreview, playbackPreview } = await fetchPreview(item)
    applyPreview(audioPreview, playbackPreview, item)
    lastAutoPreviewId.value = item.item_id
    await nextTick()
    previewAudio.value?.play().catch(() => {
      notice.value = '草稿音频已准备好；浏览器阻止自动播放时，请点击播放器的播放键。'
    })
    previewPanel.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    notice.value = '正在使用学习端同款音频/字幕/PPT/Cue 数据预览草稿。该地址仅对当前建设者有效，学生端不可见。'
  } catch (caught) {
    error.value = apiErrorMessage(caught, '该知识点尚不能试听。')
  } finally {
    acting.value = ''
  }
}

// 左侧选择即预览：当前选中知识点在批量结果中已有音频时自动加载学习端同款预览。
watch([selectedNodeDbId, batchItems], async ([nodeId]) => {
  const item = findBatchItemForScript(selectedScript.value)
  if (!item?.audio_object_key || !workingRelease.value) {
    // 选中节点没有可试听的音频，清空残留预览，避免展示上一个节点的内容。
    if (!item?.audio_object_key) {
      previewItem.value = null
      previewPlayback.value = null
    }
    return
  }
  if (acting.value || workbench?.batchRun) return
  // 轮询刷新 batch 数据时避免对同一节点重复调用预览接口
  if (lastAutoPreviewId.value === item.item_id && previewPlayback.value) return
  lastAutoPreviewId.value = item.item_id
  acting.value = `preview-${item.item_id}`
  try {
    const { audioPreview, playbackPreview } = await fetchPreview(item)
    applyPreview(audioPreview, playbackPreview, item)
    previewAudio.value?.play().catch(() => {})
  } catch {
    // 自动预览失败不打断页面；预览区会显示未生成空态。
    previewItem.value = null
    previewPlayback.value = null
  } finally {
    acting.value = ''
  }
})

async function freezeBatchPlaylist() {
  if (!workingRelease.value || acting.value) return
  acting.value = 'batch-freeze'; error.value = ''; notice.value = ''
  try {
    const result = await freezeAudioPlaylist(courseId.value, workingRelease.value.release_id, {
      batch_id: batchState.value?.batch_id || undefined,
    })
    notice.value = `已冻结 audio-playlist/v1，共 ${result.items?.length || 0} 个知识点。`
    await refreshReleaseDetail()
  } catch (caught) { error.value = apiErrorMessage(caught, '播放清单尚未满足全量成功与 PPT 映射门槛。') } finally { acting.value = '' }
}

async function selectRelease(release) {
  if (!release || release.release_id === selectedReleaseId.value) return
  selectedReleaseId.value = release.release_id
  releaseDetail.value = null
  error.value = ''
  try {
    await refreshReleaseDetail(release.release_id)
  } catch (caught) {
    error.value = apiErrorMessage(caught, '媒体版本详情读取失败。')
  }
}

async function createDraft() {
  if (!canCreateDraft.value || acting.value) return
  acting.value = 'create-release'
  error.value = ''
  notice.value = ''
  try {
    const release = await createMediaRelease(courseId.value, {
      label: `媒体验收草稿 · ${scriptLabel(selectedScript.value)}`.slice(0, 200),
      notes: '单知识点媒体验收草稿；创建后按讲稿、TTS、字幕时间轴、PPT manifest、激活顺序处理。',
      default_playback_mode: 'auto',
    })
    releases.value = [release, ...releases.value]
    selectedReleaseId.value = release.release_id
    await refreshReleaseDetail(release.release_id)
    notice.value = '媒体草稿已创建。确认计费提示后，可提交这一个知识点的语音合成。'
  } catch (caught) {
    error.value = apiErrorMessage(caught, '创建媒体草稿失败。')
  } finally {
    acting.value = ''
  }
}

function ttsPayload() {
  return {
    script_text: selectedScript.value.content,
    voice_id: 'default',
    resource_version: 'v1',
    provider_key: providerKey.value,
    // A teacher click authorizes one worker attempt.  It does not create an
    // invisible retry loop against a paid Provider.
    max_retries: 1,
  }
}

async function submitTts() {
  if (!canSubmitTts.value || acting.value) return
  acting.value = 'submit-tts'
  error.value = ''
  notice.value = ''
  try {
    const created = await createMediaGenerationJob(courseId.value, {
      job_type: 'tts',
      node_id: selectedNodeDbId.value,
      provider_key: providerKey.value,
      provider_version: provider.value?.provider_version || '',
      input_summary: `讲稿 TTS · ${scriptLabel(selectedScript.value)}`.slice(0, 500),
      input_payload: {
        source: 'teacher_media_center',
        script_node_id: selectedScript.value.script_node_id,
        script_updated_at: selectedScript.value.updated_at || null,
      },
      idempotency_key: makeTtsIdempotencyKey(),
      media_release_id: workingRelease.value.release_id,
    })
    const job = await executeMediaTtsJob(courseId.value, created.job_id, ttsPayload())
    jobs.value = [job, ...jobs.value.filter((item) => item.job_id !== job.job_id)]
    notice.value = job.status === 'succeeded'
      ? '语音已生成。现在可冻结字幕与数字人时间轴。'
      : '语音任务已提交至 Media Worker；页面会自动刷新状态。'
    await refreshReleaseDetail()
  } catch (caught) {
    error.value = apiErrorMessage(caught, '语音任务提交失败，未把失败伪装为成功。')
  } finally {
    acting.value = ''
  }
}

async function retryTts() {
  if (!canSubmitTts.value || selectedTtsJob.value?.status !== 'failed' || acting.value) return
  acting.value = 'retry-tts'
  error.value = ''
  notice.value = ''
  try {
    const job = await retryMediaGenerationJob(courseId.value, selectedTtsJob.value.job_id, ttsPayload())
    jobs.value = [job, ...jobs.value.filter((item) => item.job_id !== job.job_id)]
    notice.value = '已按你的确认重试一次语音合成；页面会自动刷新状态。'
  } catch (caught) {
    error.value = apiErrorMessage(caught, '语音重试未提交。')
  } finally {
    acting.value = ''
  }
}

async function freezeCues() {
  if (!canGenerate.value || !selectedTtsJob.value || selectedTtsJob.value.status !== 'succeeded' || acting.value) return
  acting.value = 'freeze-cues'
  error.value = ''
  notice.value = ''
  try {
    const job = await buildAvatarCues(courseId.value, workingRelease.value.release_id, {
      tts_job_id: selectedTtsJob.value.job_id,
      outline_node_id: selectedScript.value.outline_node_id,
      idempotency_key: makeCueIdempotencyKey(),
    })
    jobs.value = [job, ...jobs.value.filter((item) => item.job_id !== job.job_id)]
    notice.value = '字幕与数字人时间轴正在冻结；此步骤不会再次调用语音服务。'
  } catch (caught) {
    error.value = apiErrorMessage(caught, '字幕与数字人时间轴冻结失败。')
  } finally {
    acting.value = ''
  }
}

async function createPptManifest() {
  if (!canGenerate.value || !workingRelease.value || acting.value) return
  acting.value = 'ppt-manifest'
  error.value = ''
  notice.value = ''
  try {
    const result = await buildPptManifest(courseId.value, workingRelease.value.release_id)
    notice.value = `已冻结 ${result.page_count || 0} 张 PPT 页面。`
    await refreshReleaseDetail()
  } catch (caught) {
    error.value = apiErrorMessage(caught, 'PPT manifest 未生成。请先回到第 04 步确认 PPT 源文件和映射。')
  } finally {
    acting.value = ''
  }
}

async function activateRelease() {
  if (!canPublish.value || !canActivateWorkingRelease.value || acting.value) return
  acting.value = 'activate'
  error.value = ''
  notice.value = ''
  try {
    const release = await activateMediaRelease(courseId.value, workingRelease.value.release_id)
    releases.value = releases.value.map((item) => item.release_id === release.release_id ? release : item)
    releaseDetail.value = { ...releaseDetail.value, ...release }
    notice.value = '媒体版本已激活。仍需在第 07 步重新正式发布课程，学生端才会读取本次媒体快照。'
  } catch (caught) {
    error.value = apiErrorMessage(caught, '媒体版本未激活。')
  } finally {
    acting.value = ''
  }
}

function goToRelease() {
  router.push(`/app/course/${courseId.value}/build/releases`)
}

watch([refreshing, () => state.value], () => {
  if (workbench) {
    workbench.stageActions = {
      canRefresh: true,
      refreshing: refreshing.value || state.value === 'loading',
      onRefresh: () => load(),
      refreshLabel: '刷新状态',
    }
  }
}, { immediate: true })

watch(courseId, () => {
  selectedScriptId.value = ''
  selectedReleaseId.value = ''
  releaseDetail.value = null
  paidTtsConfirmed.value = false
  load()
})

let pollTimer = null
onMounted(() => {
  load()
  pollTimer = window.setInterval(() => {
    if (hasPendingJobs.value || activeBatchId.value) load({ quiet: true })
  }, 5000)
})
onBeforeUnmount(() => {
  window.clearInterval(pollTimer)
  if (workbench) workbench.stageActions = null
})
</script>

<template>
  <section class="media-stage">
    <SfxSkeleton v-if="state === 'loading'" :lines="7" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />

    <div v-else class="media-workbench">
      <aside class="script-rail" aria-label="可生成媒体的讲稿知识点">
        <header class="rail-header">
          <div><span>讲稿知识点</span><small>{{ scripts.length }} 个可用</small></div>
          <SfxBadge :tone="canGenerate ? 'ink' : 'red'">{{ canGenerate ? '可创建' : '无生成权限' }}</SfxBadge>
        </header>
        <p class="rail-note">点击行选中并自动试听；行首勾选参与批量生成。</p>
        <div v-if="scripts.length" class="script-list">
          <div
            v-for="script in scripts"
            :key="script.script_node_id"
            class="script-item-row"
            :class="{ selected: selectedScriptId === script.script_node_id }"
            @click="selectedScriptId = script.script_node_id"
          >
            <label class="script-check" aria-label="批量生成勾选" @click.stop>
              <input
                type="checkbox"
                :checked="batchNodeIds.includes(Number(script.script_node_db_id))"
                @change="toggleBatchNode(script)"
              />
            </label>
            <div class="script-item-copy">
              <strong>{{ scriptLabel(script) }}</strong>
              <small>{{ Array.from(script.content || '').length }} 字 · {{ script.locked ? '已锁定讲稿' : '草稿讲稿' }}</small>
            </div>
            <SfxButton
              v-if="scriptItemAudio(script)"
              variant="secondary"
              size="sm"
              :loading="acting === `preview-${scriptItemAudio(script).item_id}`"
              class="script-item-listen"
              @click.stop="previewBatchItem(scriptItemAudio(script))"
            ><Volume2 :size="14" /> 试听</SfxButton>
          </div>
        </div>
        <div v-else class="rail-empty">
          <Sparkles :size="22" />
          <strong>还没有可用讲稿</strong>
          <p>先在第 03 步生成并确认一个有正文的讲稿知识点。</p>
        </div>
      </aside>

      <main class="media-main">
        <div class="provider-runtime-banner" role="status">
          <SfxBadge v-if="providerReady" :tone="providerIsDemo ? 'ink' : 'green'">{{ providerDisplayName }}</SfxBadge>
          <SfxBadge v-else tone="red">Stage 8 Provider 未就绪</SfxBadge>
          <span>{{ provider?.message || providerError || '正在读取服务端 Provider 状态' }}</span>
        </div>
        <div class="provider-bar" aria-label="语音服务状态">
          <SfxBadge v-if="providerReady" tone="green">语音服务可用</SfxBadge>
          <SfxBadge v-else-if="providerError" tone="red">语音服务未确认</SfxBadge>
          <SfxBadge v-else tone="amber">正在确认语音服务</SfxBadge>
          <span v-if="providerReady" class="provider-bar-name">{{ providerDisplayName }}</span>
        </div>
        <p v-if="providerReady" class="provider-runtime-status" role="status">{{ providerDisplayName }}：{{ provider?.message }}</p>
        <p v-else-if="provider?.message" class="provider-runtime-status is-blocked" role="alert">{{ provider?.message }}</p>
        <p v-if="notice" class="notice" role="status">{{ notice }}</p>
        <p v-if="error" class="action-error" role="alert"><CircleAlert :size="16" /> {{ error }}</p>
        <p v-if="providerError" class="action-error" role="alert"><CircleAlert :size="16" /> {{ providerError }}</p>

        <section class="release-panel batch-panel" aria-labelledby="batch-title">
          <header class="panel-heading">
            <div><p>P4 批量媒体建设</p><h3 id="batch-title">在左侧勾选知识点，一次确认后批量生成</h3></div>
            <SfxBadge tone="ink">{{ batchNodeIds.length }} / 20</SfxBadge>
          </header>
          <div v-if="presetCatalog.voices.length || presetCatalog.avatars.length" class="preset-selection">
            <div class="preset-group">
              <span class="preset-label">平台音色</span>
              <label v-for="voice in presetCatalog.voices" :key="`voice-${voice.preset_id}-${voice.version}`" class="preset-option" :class="{ selected: selectedVoicePresetId === voice.preset_id && selectedVoicePresetVersion === voice.version }">
                <input v-model="selectedVoicePresetId" type="radio" name="media-voice-preset" :value="voice.preset_id" @change="selectedVoicePresetVersion = voice.version" />
                <span><strong>{{ voice.display_name }}</strong><small>{{ voice.version }} · {{ voice.provider_key }}</small></span>
              </label>
            </div>
            <div class="preset-group">
              <span class="preset-label">平台 2D 角色</span>
              <label v-for="avatarPreset in presetCatalog.avatars" :key="`avatar-${avatarPreset.preset_id}-${avatarPreset.version}`" class="preset-option" :class="{ selected: selectedAvatarPresetId === avatarPreset.preset_id && selectedAvatarPresetVersion === avatarPreset.version }">
                <input v-model="selectedAvatarPresetId" type="radio" name="media-avatar-preset" :value="avatarPreset.preset_id" @change="selectedAvatarPresetVersion = avatarPreset.version" />
                <span><strong>{{ avatarPreset.display_name }}</strong><small>{{ avatarPreset.version }} · {{ avatarPreset.manifest_available ? 'manifest 可用' : 'manifest 缺失' }}</small></span>
              </label>
            </div>
          </div>
          <div v-if="batchPlan" class="batch-estimate">
            <span>节点 {{ batchPlan.node_count }}</span><span>总字符 {{ batchPlan.total_chars }}</span><span>待计费 {{ batchPlan.billable_chars }}</span><span>缓存命中 {{ batchPlan.cache_hit_count }}</span>
            <p v-if="batchPlan.blocking_reasons?.length" class="task-error">{{ [...new Set(batchPlan.blocking_reasons)].join('；') }}；试听可随时进行，但最终发布前需完成全部映射。</p>
            <p v-if="!batchPlanMatchesSelections" class="task-error">音色或角色已变更，请重新核算后再确认；不能用旧估算冻结新版本。</p>
          </div>
          <div class="tts-actions">
            <span v-if="providerIsDemo" class="provider-demo-note">演示模式：使用本地合成，不产生费用。</span>
            <SfxButton :disabled="!canPlanBatch" :loading="acting === 'batch-plan'" @click="createBatchPlan">核算批量费用</SfxButton>
            <label v-if="providerNeedsConfirmation" class="confirmation-check"><input v-model="paidTtsConfirmed" type="checkbox" :disabled="!batchPlan" /> 我确认本批可能产生 TTS Provider 费用</label>
            <SfxButton :disabled="!canConfirmBatch" :loading="acting === 'batch-confirm'" @click="confirmBatch">确认并提交批量任务</SfxButton>
          </div>
          <div v-if="batchState" class="batch-status" role="status">
            <span>批次状态：{{ batchStatusLabel(batchState.status) }}</span>
            <span>已完成 {{ batchItems.filter(item => item.status === 'ready').length }} / {{ batchItems.length }}</span>
          </div>
          <div v-if="batchState || batchItems.length" class="step-pipeline" aria-label="媒体建设六步流程">
            <div v-for="step in batchSteps" :key="step.key" class="step" :class="{ done: step.done, active: step.active }">
              <span class="step-index">{{ step.key }}</span>
              <span class="step-label">{{ step.label }}</span>
            </div>
          </div>
          <div v-if="batchItems.length" class="batch-item-list" aria-label="批量媒体节点状态">
            <article v-for="item in batchItems" :key="item.item_id || item.node_id" class="batch-item-row">
              <div><strong>{{ findScriptForBatchItem(item) ? scriptLabel(findScriptForBatchItem(item)) : `知识点 ${item.node_id}` }}</strong><small>{{ batchItemStatusLabel(item.status) }}{{ item.error_message_safe ? ` · ${item.error_message_safe}` : '' }}</small></div>
              <SfxBadge :tone="item.status === 'ready' ? 'green' : item.status === 'failed' || item.status === 'blocked' ? 'red' : 'amber'">{{ batchItemStatusLabel(item.status) }}</SfxBadge>
            </article>
          </div>
        </section>

        <template v-if="selectedScript">
          <section class="selected-script" aria-labelledby="selected-script-title">
            <div class="selected-script-heading">
              <span>当前讲稿</span>
              <h3 id="selected-script-title">{{ scriptLabel(selectedScript) }}</h3>
              <p>{{ selectedCharCount }} 字 · {{ selectedByteCount }} UTF-8 字节 · {{ selectedScript.locked ? '已锁定，不会在媒体处理中改写' : '草稿内容将按本次提交固定' }}</p>
            </div>
            <div class="script-preview">{{ selectedScript.content }}</div>
          </section>

          <!-- 学习端同款预览：跟随左侧选中的知识点；批量列表“试听”会同步左侧选择并定位到这里 -->
          <section ref="previewPanel" class="preview-panel" aria-labelledby="preview-title">
            <header class="panel-heading">
              <div>
                <p>学习端同款预览</p>
                <h3 id="preview-title">{{ previewPlayback ? previewNodeLabel : scriptLabel(selectedScript) }}</h3>
              </div>
              <SfxBadge :tone="previewPlayback ? 'green' : 'neutral'">{{ previewPlayback ? '可试听' : '未生成' }}</SfxBadge>
            </header>
            <div v-if="previewPlayback" class="preview-body">
              <p v-if="previewPlayback.ppt_timeline?.length">PPT：{{ previewPlayback.ppt_timeline.map(item => `第 ${item.ppt_page} 页`).join('、') }}</p>
              <p v-else>PPT 映射尚未完成；试听可正常进行，但最终发布需要先完成映射。</p>
              <p v-if="previewPlayback.subtitle_segments?.length">字幕：{{ previewPlayback.subtitle_segments.map(item => item.text).join('') }}</p>
              <p v-else>字幕与数字人时间轴尚未生成；试听可正常进行，但最终发布需要先生成。</p>
            </div>
            <div v-else class="preview-empty">
              <Volume2 :size="20" />
              <p>{{ selectedBatchItem?.audio_object_key ? '正在准备学习端同款预览…' : '该知识点尚未生成音频。在批量面板完成生成后，选中节点即可自动试听；也可在批量列表中点击“试听”。' }}</p>
            </div>
          </section>

          <section class="release-panel" aria-labelledby="release-title">
            <header class="panel-heading">
              <div>
                <p>媒体版本与处理流程</p>
                <h3 id="release-title">{{ workingRelease ? workingRelease.label || `媒体版本 ${workingRelease.version_number}` : '尚未创建媒体草稿' }}</h3>
              </div>
              <SfxBadge v-if="workingRelease" :tone="releaseTone(workingRelease)">{{ releaseStatusLabel(workingRelease) }}</SfxBadge>
            </header>

            <div v-if="releases.length" class="release-picker" aria-label="课程媒体版本">
              <SfxButton
                v-for="release in releases"
                :key="release.release_id"
                size="sm"
                :variant="release.release_id === workingRelease?.release_id ? 'primary' : 'tertiary'"
                @click="selectRelease(release)"
              >v{{ release.version_number }} · {{ releaseStatusLabel(release) }}</SfxButton>
            </div>

            <div v-if="!workingRelease" class="release-empty">
              <FileImage :size="23" />
              <div><strong>先创建一个媒体验收草稿</strong><p>草稿不会影响当前已激活或学生可见的媒体版本。</p></div>
              <SfxButton :disabled="!canCreateDraft" :loading="acting === 'create-release'" @click="createDraft">创建媒体验收草稿</SfxButton>
            </div>

            <template v-else>
              <div v-if="!releaseMatchesSelection" class="binding-warning">
                <CircleAlert :size="18" />
                <div><strong>此草稿已绑定其他知识点</strong><p>它正在处理「{{ scriptLabel(boundScript) }}」。一个草稿当前只支持一段知识点音频；为当前讲稿请新建草稿。</p></div>
                <SfxButton size="sm" :disabled="!canCreateDraft" :loading="acting === 'create-release'" @click="createDraft">新建草稿</SfxButton>
              </div>

              <div v-else class="workflow-list">
                <article class="workflow-row" :class="{ complete: Boolean(selectedTtsJob?.status === 'succeeded'), active: !selectedTtsJob }">
                  <div class="workflow-icon"><Volume2 :size="18" /></div>
                  <div class="workflow-copy"><span>01 · 语音合成</span><strong>将当前讲稿提交给已配置的服务器端音色</strong><p v-if="selectedTtsJob">{{ jobStatusLabel(selectedTtsJob) }} · {{ selectedTtsJob.output_metadata?.cache_hit ? '命中已有音频缓存' : selectedTtsJob.error_message_safe || '任务状态会自动刷新' }}</p><p v-else>提交前需教师明确确认；页面不会读取或展示任何密钥、音色 ID。</p></div>
                  <SfxBadge v-if="selectedTtsJob" :tone="jobTone(selectedTtsJob)">{{ jobStatusLabel(selectedTtsJob) }}</SfxBadge>
                </article>

                <div v-if="!selectedTtsJob || selectedTtsJob.status === 'failed'" class="tts-confirmation">
                  <label v-if="providerNeedsConfirmation" class="confirmation-check"><input v-model="paidTtsConfirmed" type="checkbox" :disabled="!providerReady || !canGenerate" /><span>我确认本次将提交一次语音合成，并承担正式 Provider 调用费用。</span></label>
                  <span v-else-if="providerIsDemo" class="provider-demo-note">演示模式：无需费用确认，仅生成可试听的演示音频。</span>
                  <div class="tts-actions">
                    <SfxButton v-if="selectedTtsJob?.status === 'failed'" :disabled="!canSubmitTts" :loading="acting === 'retry-tts'" @click="retryTts">确认并重试一次</SfxButton>
                    <SfxButton v-else :disabled="!canSubmitTts" :loading="acting === 'submit-tts'" @click="submitTts"><Send :size="16" /> 提交语音合成</SfxButton>
                    <small v-if="!providerReady">先等待服务器端语音服务健康检查通过。</small>
                  </div>
                </div>

                <article class="workflow-row" :class="{ complete: releaseCueAssetsReady, active: selectedTtsJob?.status === 'succeeded' && !releaseCueAssetsReady }">
                  <div class="workflow-icon"><Captions :size="18" /></div>
                  <div class="workflow-copy"><span>02 · 字幕与数字人时间轴</span><strong>冻结字幕、说话区间和 PPT 映射快照</strong><p v-if="isPlaylistRelease && batchReady">本批全部知识点均已生成 release-scoped subtitle-manifest/v1 与 avatar-cues/v1。</p><p v-else-if="hasFrozenCues">已生成 release-scoped subtitle-manifest/v1 与 avatar-cues/v1。</p><p v-else-if="cueJob">{{ jobStatusLabel(cueJob) }} · {{ cueJob.error_message_safe || '不再调用 TTS Provider' }}</p><p v-else>需要成功 TTS；缺少音素时仅生成字级/字幕驱动的通用说话状态，不宣称精确口型。</p></div>
                  <SfxBadge :tone="releaseCueAssetsReady ? 'green' : cueJob ? jobTone(cueJob) : 'neutral'">{{ releaseCueAssetsReady ? '已冻结' : cueJob ? jobStatusLabel(cueJob) : '等待 TTS' }}</SfxBadge>
                </article>
                <div v-if="selectedTtsJob?.status === 'succeeded' && !hasFrozenCues && (!cueJob || cueJob.status === 'failed')" class="workflow-action"><SfxButton :disabled="!canGenerate" :loading="acting === 'freeze-cues'" @click="freezeCues">冻结字幕与数字人时间轴</SfxButton></div>

                <article class="workflow-row" :class="{ complete: hasPptManifest, active: canBuildPptManifest && !hasPptManifest }">
                  <div class="workflow-icon"><FileImage :size="18" /></div>
                  <div class="workflow-copy"><span>03 · PPT manifest</span><strong>冻结学生端播放所需的 PPT 页图清单</strong><p v-if="hasPptManifest">PPT manifest 已绑定到此媒体草稿。</p><p v-else-if="isPlaylistRelease">批量模式：需全部知识点音频与 Cue 就绪后生成；缺少 PPT 源文件时服务端会返回明确阻塞原因。</p><p v-else>如果第 04 步尚无可渲染 PPT/PDF 源文件，本步骤会明确返回阻塞原因；可先回到映射页处理。</p></div>
                  <SfxBadge :tone="hasPptManifest ? 'green' : 'amber'">{{ hasPptManifest ? '已冻结' : '可选但建议完成' }}</SfxBadge>
                </article>
                <div v-if="canBuildPptManifest && !hasPptManifest" class="workflow-action"><SfxButton variant="secondary" :disabled="!canGenerate" :loading="acting === 'ppt-manifest'" @click="createPptManifest">生成 PPT manifest</SfxButton></div>
                <div v-if="isPlaylistRelease" class="workflow-action">
                  <p v-if="hasFrozenPlaylist" class="task-output">课程播放清单已固定到此版本，后续不会自动更改。</p>
                  <SfxButton v-else variant="secondary" :disabled="!canGenerate || !hasPptManifest" :loading="acting === 'batch-freeze'" @click="freezeBatchPlaylist">冻结课程播放清单</SfxButton>
                  <small v-if="!hasPptManifest">需先完成 PPT 页面映射；有知识点未生成或映射缺失时，无法最终发布。</small>
                </div>

                <article class="workflow-row" :class="{ complete: workingRelease.status === 'active', active: canActivateWorkingRelease && workingRelease.status === 'draft' }">
                  <div class="workflow-icon"><Check :size="18" /></div>
                  <div class="workflow-copy"><span>04 · 激活并固化到课程发布</span><strong>激活媒体版本，再重新正式发布课程</strong><p v-if="workingRelease.status === 'active'">媒体已激活；课程正式发布时会把它写入不可变媒体快照。</p><p v-else>激活不会自动改写学生当前课程版本。完成激活后仍需到第 07 步重新正式发布。</p></div>
                  <SfxBadge :tone="workingRelease.status === 'active' ? 'green' : 'amber'">{{ workingRelease.status === 'active' ? '已激活' : '等待激活' }}</SfxBadge>
                </article>
                <div v-if="workingRelease.status === 'draft'" class="workflow-action"><SfxButton :disabled="!canPublish || !canActivateWorkingRelease" :loading="acting === 'activate'" @click="activateRelease">激活媒体版本</SfxButton></div>
                <div v-else-if="workingRelease.status === 'active'" class="workflow-action"><SfxButton @click="goToRelease">前往正式发布</SfxButton></div>
              </div>
            </template>
          </section>

          <section class="task-panel" aria-labelledby="task-title">
            <header class="panel-heading">
              <div><p>已提交的合成与冻结任务</p><h3 id="task-title">媒体任务记录</h3></div>
              <SfxButton variant="tertiary" size="sm" :loading="refreshing" @click="load"><RefreshCw :size="14" /> 刷新</SfxButton>
            </header>
            <div v-if="jobs.length" class="task-list">
              <article v-for="job in jobs.slice(0, 12)" :key="job.job_id" class="task-row">
                <div><strong>{{ jobLabel(job) }}</strong><span>{{ scripts.find((item) => item.script_node_db_id === job.node_id) ? scriptLabel(scripts.find((item) => item.script_node_db_id === job.node_id)) : '未关联讲稿节点' }}</span></div>
                <SfxBadge :tone="jobTone(job)">{{ jobStatusLabel(job) }}</SfxBadge>
                <span class="task-time">{{ formatDate(job.finished_at || job.created_at) }}</span>
                <p v-if="job.error_message_safe" class="task-error">{{ job.error_message_safe }}</p>
                <p v-else-if="job.output_object_key" class="task-output">已生成受课程权限保护的媒体对象</p>
              </article>
            </div>
            <p v-else class="task-empty">还没有媒体任务。创建草稿并明确提交 TTS 后，状态会在这里保留。</p>
          </section>

        </template>
        <div v-else class="main-empty"><Sparkles :size="28" /><strong>先生成讲稿，再创建课堂媒体</strong><p>媒体中心只处理已确认的讲稿节点，因此不会凭空生成或猜测教学内容。</p></div>

        <div v-if="previewItem?.audio_url" class="preview-dock" role="region" aria-label="试听播放器">
          <span class="preview-dock-label">试听</span>
          <audio ref="previewAudio" :key="previewItem.audio_url" :src="previewItem.audio_url" controls preload="metadata" />
        </div>
      </main>
    </div>
  </section>
</template>

<style scoped>
.batch-panel{border:1px solid var(--border-strong);background:var(--surface-soft)}.batch-estimate{display:flex;flex-wrap:wrap;gap:var(--space-4);padding:var(--space-3) var(--space-4);color:var(--text-secondary);font-size:var(--ui-sm-size)}.batch-estimate p{flex-basis:100%;margin:0}.batch-status{display:flex;flex-wrap:wrap;gap:var(--space-3);padding:var(--space-2) var(--space-4);border-top:1px solid var(--border-subtle);color:var(--text-secondary);font-size:var(--caption-size)}.step-pipeline{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:var(--space-2);padding:var(--space-3) var(--space-4);border-top:1px solid var(--border-subtle)}.step{display:grid;gap:3px;padding:var(--space-2);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);background:var(--surface-panel)}.step-index{color:var(--text-muted);font-family:var(--font-mono);font-size:11px;letter-spacing:.04em}.step-label{color:var(--text-secondary);font-size:var(--caption-size);font-weight:600;line-height:1.3;overflow-wrap:anywhere}.step.active{border-color:var(--ink-400);background:var(--ink-100)}.step.active .step-index{color:var(--ink-700)}.step.done{border-color:var(--green-300);background:var(--green-100)}.step.done .step-index{color:var(--green-700)}.step.done .step-label{color:var(--green-800)}.batch-item-list{display:grid;border-top:1px solid var(--border-subtle)}.batch-item-row{display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);padding:var(--space-2) var(--space-4);border-bottom:1px solid var(--border-subtle)}.batch-item-row>div{display:grid;gap:2px;min-width:0}.batch-item-row strong{color:var(--text-primary);font-size:var(--ui-sm-size)}.batch-item-row small{color:var(--text-secondary);font-size:var(--caption-size);overflow-wrap:anywhere}
.media-stage{height:100%;min-height:0;display:grid;grid-template-rows:minmax(0,1fr);overflow:hidden}
.media-workbench{display:grid;grid-template-columns:272px minmax(0,1fr);grid-template-rows:minmax(0,1fr);min-height:0;border:1px solid var(--border-default);border-radius:var(--radius-lg);overflow:hidden;background:var(--surface-canvas)}
.script-rail{display:flex;flex-direction:column;min-height:0;background:var(--surface-panel);border-right:1px solid var(--border-default)}.rail-header{display:flex;align-items:center;justify-content:space-between;gap:var(--space-2);padding:var(--space-3);border-bottom:1px solid var(--border-subtle)}.rail-header>div{display:grid;gap:1px}.rail-header span{color:var(--text-primary);font-size:var(--ui-md-size);font-weight:650}.rail-header small,.rail-note{color:var(--text-muted);font-size:var(--caption-size)}.rail-note{margin:0;padding:var(--space-2) var(--space-3);border-bottom:1px solid var(--border-subtle);line-height:1.45}.script-list{display:grid;align-content:start;gap:var(--space-1);min-height:0;overflow-y:auto;padding:var(--space-2)}
.script-item-row{display:flex;align-items:center;gap:var(--space-2);min-height:54px;padding:var(--space-2);border:1px solid transparent;border-radius:var(--radius-md);cursor:pointer;transition:background var(--duration-fast) var(--ease-out)}
.script-item-row:hover{background:var(--surface-cool)}
.script-item-row.selected{background:var(--ink-100);border-color:var(--ink-300)}
.script-check{display:grid;place-items:center;flex-shrink:0}
.script-check input{width:16px;height:16px;margin:0;accent-color:var(--ink-700);cursor:pointer}
.script-item-copy{display:grid;min-width:0;flex:1;gap:2px}
.script-item-copy strong{font-size:var(--ui-sm-size);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.script-item-copy small{font-size:11px;opacity:.8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.script-item-listen{flex-shrink:0}
.rail-empty{display:grid;justify-items:center;gap:var(--space-2);margin:auto;padding:var(--space-6);color:var(--text-muted);text-align:center}.rail-empty strong{color:var(--text-primary);font-size:var(--ui-md-size)}.rail-empty p{margin:0;font-size:var(--caption-size);line-height:1.5}
.media-main{display:flex;flex-direction:column;gap:var(--space-3);min-width:0;min-height:0;overflow-y:auto;padding:var(--space-3) var(--space-6)}.provider-runtime-banner{display:flex;align-items:center;gap:var(--space-2);padding:var(--space-2) var(--space-3);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);background:var(--surface-cool);color:var(--text-secondary);font-size:var(--ui-sm-size)}.provider-runtime-status{margin:0;color:var(--text-secondary);font-size:var(--caption-size)}.provider-runtime-status.is-blocked{color:var(--red-700)}.provider-demo-note{color:var(--ink-700);font-size:var(--caption-size)}.provider-bar{display:flex;align-items:center;gap:var(--space-2);flex-shrink:0}.provider-bar-name{color:var(--text-muted);font-family:var(--font-mono);font-size:11px}.notice,.action-error{display:flex;align-items:flex-start;gap:var(--space-2);margin:0;padding:var(--space-3);border-radius:var(--radius-md);font-size:var(--ui-sm-size);line-height:1.5;flex-shrink:0}.notice{border:1px solid var(--ink-300);background:var(--ink-100);color:var(--ink-700)}.action-error{border:1px solid var(--red-300);background:var(--red-100);color:var(--red-700)}
.preview-panel{border:1px solid var(--border-default);border-radius:var(--radius-md);background:var(--surface-panel);overflow:hidden;flex-shrink:0;scroll-margin-top:var(--space-3)}
.preset-selection{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:var(--space-3);padding:var(--space-3) var(--space-4);border-bottom:1px solid var(--border-subtle);background:var(--surface-cool)}.preset-group{display:grid;gap:var(--space-2);min-width:0}.preset-label{color:var(--text-muted);font-size:var(--caption-size);font-weight:600;letter-spacing:.04em}.preset-option{display:flex;align-items:flex-start;gap:var(--space-2);padding:var(--space-2);border:1px solid var(--border-default);border-radius:var(--radius-sm);background:var(--surface-panel);cursor:pointer}.preset-option.selected{border-color:var(--ink-500);background:var(--ink-100)}.preset-option input{width:16px;height:16px;margin:2px 0 0;accent-color:var(--ink-700);flex-shrink:0}.preset-option span{display:grid;gap:2px;min-width:0}.preset-option strong{color:var(--text-primary);font-size:var(--ui-sm-size)}.preset-option small{color:var(--text-secondary);font-size:var(--caption-size);overflow-wrap:anywhere}
.preview-body{display:grid;gap:var(--space-2);padding:var(--space-3) var(--space-4)}
.preview-body p{margin:0;color:var(--text-secondary);font-size:var(--ui-sm-size);line-height:1.55;overflow-wrap:anywhere}
.preview-empty{display:flex;align-items:flex-start;gap:var(--space-2);padding:var(--space-4);color:var(--text-muted);font-size:var(--ui-sm-size);line-height:1.5}
.preview-empty p{margin:0}
.preview-dock{position:sticky;bottom:calc(var(--space-3) * -1);display:flex;align-items:center;gap:var(--space-3);margin:0 calc(var(--space-6) * -1) calc(var(--space-3) * -1);padding:var(--space-2) var(--space-4);background:var(--surface-panel);border-top:1px solid var(--border-default);flex-shrink:0;z-index:5}.preview-dock-label{font-size:var(--caption-size);font-weight:600;letter-spacing:.04em;color:var(--text-muted);flex-shrink:0}.preview-dock audio{flex:1;min-width:0;height:36px}
.selected-script{display:grid;grid-template-columns:minmax(180px,.6fr) minmax(0,1.4fr);gap:var(--space-4);padding:var(--space-4);border-left:3px solid var(--ink-500);background:var(--surface-cool);max-height:340px;min-height:140px;overflow:hidden;flex-shrink:0}.selected-script-heading{display:grid;align-content:start;gap:var(--space-1);overflow-y:auto;min-height:0}.selected-script-heading>span,.panel-heading p,.workflow-copy>span{color:var(--text-muted);font-size:var(--caption-size);font-weight:600;letter-spacing:.04em}.selected-script-heading h3{margin:0;color:var(--text-primary);font-size:var(--title-3-size);line-height:var(--title-3-line)}.selected-script-heading p{margin:0;color:var(--text-secondary);font-size:var(--caption-size);line-height:1.5}.script-preview{max-height:100%;overflow-y:auto;color:var(--text-primary);font-size:var(--ui-sm-size);line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere}
.release-panel,.task-panel{border:1px solid var(--border-default);border-radius:var(--radius-md);background:var(--surface-panel);overflow:hidden;flex-shrink:0}.panel-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-3);padding:var(--space-3) var(--space-4);border-bottom:1px solid var(--border-subtle)}.panel-heading p{margin:0}.panel-heading h3{margin:2px 0 0;color:var(--text-primary);font-size:var(--ui-md-size)}.release-picker{display:flex;gap:var(--space-1);overflow-x:auto;padding:var(--space-2) var(--space-3);border-bottom:1px solid var(--border-subtle)}.release-empty{display:flex;align-items:center;gap:var(--space-3);padding:var(--space-6);color:var(--text-muted)}.release-empty>div{display:grid;gap:var(--space-1);min-width:0;flex:1}.release-empty strong{color:var(--text-primary);font-size:var(--ui-md-size)}.release-empty p{margin:0;font-size:var(--ui-sm-size);line-height:1.5}.binding-warning{display:grid;grid-template-columns:20px minmax(0,1fr) auto;align-items:start;gap:var(--space-2);padding:var(--space-4);background:var(--amber-100);color:var(--amber-700)}.binding-warning div{display:grid;gap:var(--space-1)}.binding-warning strong{color:var(--text-primary);font-size:var(--ui-md-size)}.binding-warning p{margin:0;font-size:var(--ui-sm-size);line-height:1.5}
.workflow-list{display:grid}.workflow-row{display:grid;grid-template-columns:34px minmax(0,1fr) auto;gap:var(--space-3);align-items:start;padding:var(--space-4);border-bottom:1px solid var(--border-subtle)}.workflow-row.active{background:var(--ink-100)}.workflow-row.complete{background:var(--green-100)}.workflow-icon{display:grid;place-items:center;width:32px;height:32px;border-radius:var(--radius-full);background:var(--surface-cool);color:var(--ink-700)}.workflow-row.complete .workflow-icon{background:var(--surface-panel);color:var(--green-700)}.workflow-copy{display:grid;gap:2px;min-width:0}.workflow-copy strong{color:var(--text-primary);font-size:var(--ui-md-size);line-height:1.45}.workflow-copy p{margin:0;color:var(--text-secondary);font-size:var(--ui-sm-size);line-height:1.5}.tts-confirmation,.workflow-action{margin:0 0 var(--space-3);padding:var(--space-3);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);background:var(--surface-cool)}.confirmation-check{display:flex;align-items:flex-start;gap:var(--space-2);color:var(--text-secondary);font-size:var(--ui-sm-size);line-height:1.5}.confirmation-check input{width:16px;height:16px;margin:2px 0 0;accent-color:var(--ink-700);flex-shrink:0}.tts-actions{display:flex;align-items:center;gap:var(--space-3);margin-top:var(--space-3)}.tts-actions small{color:var(--text-muted);font-size:var(--caption-size)}.workflow-action{display:flex;justify-content:flex-end;padding:0;border:0;background:transparent}
.task-list{display:grid;max-height:280px;overflow-y:auto}.task-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:var(--space-3);align-items:center;padding:var(--space-3) var(--space-4);border-bottom:1px solid var(--border-subtle)}.task-row:last-child{border-bottom:0}.task-row>div{display:grid;gap:2px;min-width:0}.task-row strong,.task-row span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.task-row strong{color:var(--text-primary);font-size:var(--ui-sm-size)}.task-row span{color:var(--text-muted);font-size:var(--caption-size)}.task-time{justify-self:end;white-space:nowrap}.task-row .task-error,.task-row .task-output{grid-column:1/-1;margin:0;font-size:var(--caption-size);line-height:1.45}.task-error{color:var(--red-700)}.task-output{color:var(--green-700)}.task-empty{margin:0;padding:var(--space-6);color:var(--text-muted);font-size:var(--ui-sm-size);text-align:center}.main-empty{display:grid;place-items:center;align-content:center;gap:var(--space-2);min-height:300px;color:var(--text-muted);text-align:center}.main-empty strong{color:var(--text-primary);font-size:var(--title-3-size)}.main-empty p{max-width:380px;margin:0;font-size:var(--ui-sm-size);line-height:1.5}
@media(max-width:960px){.media-workbench{grid-template-columns:220px minmax(0,1fr)}.selected-script{grid-template-columns:1fr;max-height:none}.task-row{grid-template-columns:minmax(0,1fr) auto}.task-time{display:none}}
@media(max-width:700px){.media-stage{height:auto;overflow:visible}.media-workbench{grid-template-columns:1fr;grid-template-rows:auto auto;overflow:visible}.script-rail{max-height:260px;border-right:0;border-bottom:1px solid var(--border-default)}.media-main{overflow:visible;padding:var(--space-3)}.selected-script{max-height:none;overflow:visible}.selected-script-heading{overflow:visible}.workflow-row{grid-template-columns:34px minmax(0,1fr)}.workflow-row>.sfx-badge{grid-column:2}.binding-warning{grid-template-columns:20px minmax(0,1fr)}.binding-warning .sfx-btn{grid-column:2;justify-self:start}.release-empty{align-items:flex-start;flex-wrap:wrap}.release-empty .sfx-btn{margin-left:35px}.tts-actions{align-items:flex-start;flex-direction:column}.task-list{max-height:none;overflow:visible}.task-row{grid-template-columns:minmax(0,1fr) auto}}
@media(max-width:700px){.preset-selection{grid-template-columns:1fr}}
</style>
