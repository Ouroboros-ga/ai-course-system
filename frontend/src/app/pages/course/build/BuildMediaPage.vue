<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AudioLines, Captions, Check, ChevronDown, CircleAlert, FileImage, RefreshCw, Send, Sparkles, Volume2, X } from 'lucide-vue-next'
import { getTeachingScripts } from '@/api/course_editor.js'
import {
  activateMediaRelease,
  buildAvatarCues,
  buildPptManifest,
  createMediaGenerationJob,
  createMediaRelease,
  executeMediaTtsJob,
  getMediaProviderHealth,
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
const selectedScriptId = ref('')
const selectedReleaseId = ref('')
const paidTtsConfirmed = ref(false)
const acting = ref('')
const refreshing = ref(false)

// 顶部介绍卡可折叠：折叠后给下方工作区让出垂直空间（状态按设备记忆）
const BRIEF_STORAGE_KEY = 'sfx:build:media-brief-hidden'
const briefHidden = ref(false)
try {
  if (localStorage.getItem(BRIEF_STORAGE_KEY) === '1') briefHidden.value = true
} catch { /* localStorage 不可用时保持默认 */ }
watch(briefHidden, (value) => {
  try { localStorage.setItem(BRIEF_STORAGE_KEY, value ? '1' : '0') } catch { /* ignore */ }
})

const allowed = computed(() => courseContext?.allowed?.value ?? {})
const canGenerate = computed(() => Boolean(allowed.value['course.media.generate']))
const canPublish = computed(() => Boolean(allowed.value['course.publish']))
const selectedScript = computed(() => scripts.value.find((item) => item.script_node_id === selectedScriptId.value) ?? null)
const selectedNodeDbId = computed(() => Number(selectedScript.value?.script_node_db_id) || null)
const draftReleases = computed(() => releases.value.filter((item) => item.status === 'draft'))
const workingRelease = computed(() => releaseDetail.value ?? releases.value.find((item) => item.release_id === selectedReleaseId.value) ?? null)
const provider = computed(() => providerHealth.value?.tts ?? null)
const providerKey = computed(() => provider.value?.provider_key || '')
const providerReady = computed(() => Boolean(provider.value?.healthy && providerKey.value))
const selectedCharCount = computed(() => Array.from(selectedScript.value?.content || '').length)
const selectedByteCount = computed(() => new TextEncoder().encode(selectedScript.value?.content || '').length)

const releaseTtsJobs = computed(() => jobs.value.filter((job) => (
  job.job_type === 'tts' && job.media_release_id === workingRelease.value?.release_id
)))
const releaseTtsJob = computed(() => releaseTtsJobs.value[0] ?? null)
const selectedTtsJob = computed(() => releaseTtsJobs.value.find((job) => job.node_id === selectedNodeDbId.value) ?? null)
const releaseBoundNodeId = computed(() => releaseTtsJob.value?.node_id ?? workingRelease.value?.cues?.[0]?.node_id ?? null)
const releaseMatchesSelection = computed(() => !releaseBoundNodeId.value || releaseBoundNodeId.value === selectedNodeDbId.value)
const boundScript = computed(() => scripts.value.find((item) => item.script_node_db_id === releaseBoundNodeId.value) ?? null)
const cueJob = computed(() => jobs.value.find((job) => (
  job.job_type === 'timeline_publish' && job.media_release_id === workingRelease.value?.release_id
)) ?? null)
const hasFrozenCues = computed(() => Boolean(
  workingRelease.value?.avatar_cues_object_key && workingRelease.value?.subtitle_manifest_object_key,
))
const hasPptManifest = computed(() => Boolean(workingRelease.value?.ppt_manifest_object_key))
const hasPendingJobs = computed(() => jobs.value.some((job) => ['pending', 'running'].includes(job.status)))
const canCreateDraft = computed(() => Boolean(canGenerate.value && selectedNodeDbId.value && selectedScript.value?.content?.trim()))
const canSubmitTts = computed(() => Boolean(
  canCreateDraft.value
  && workingRelease.value?.status === 'draft'
  && releaseMatchesSelection.value
  && providerReady.value
  && paidTtsConfirmed.value
  && !['pending', 'running'].includes(selectedTtsJob.value?.status),
))

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

function scriptLabel(script) {
  return script?.display_label || script?.outline_title || script?.script_node_id || '未关联知识点'
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
  return `tts:${workingRelease.value.release_id}:${selectedNodeDbId.value}:${revision || 'initial'}`
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

async function load({ quiet = false } = {}) {
  if (acting.value || refreshing.value) return
  if (!quiet) state.value = state.value === 'ready' ? 'refreshing' : 'loading'
  refreshing.value = true
  error.value = ''
  providerError.value = ''
  try {
    const [scriptData, jobData, releaseData, healthResult] = await Promise.all([
      getTeachingScripts(courseId.value),
      listMediaGenerationJobs(courseId.value),
      listMediaReleases(courseId.value),
      getMediaProviderHealth().catch((caught) => ({ __error: caught })),
    ])
    scripts.value = (scriptData?.items ?? []).filter((item) => (
      Number(item.script_node_db_id) > 0 && Boolean(item.content?.trim())
    ))
    jobs.value = jobData?.items ?? []
    releases.value = releaseData?.items ?? []
    providerHealth.value = healthResult?.__error ? null : healthResult
    providerError.value = healthResult?.__error
      ? apiErrorMessage(healthResult.__error, '无法确认语音服务状态，已阻止提交合成。')
      : ''
    if (!scripts.value.some((item) => item.script_node_id === selectedScriptId.value)) {
      selectedScriptId.value = scripts.value[0]?.script_node_id || ''
    }
    selectedReleaseId.value = chooseDefaultRelease(releases.value)
    await refreshReleaseDetail()
    state.value = 'ready'
  } catch (caught) {
    error.value = apiErrorMessage(caught, '媒体创建中心暂时无法读取课程数据。')
    state.value = 'error'
  } finally {
    refreshing.value = false
  }
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
  if (!canPublish.value || !hasFrozenCues.value || workingRelease.value?.status !== 'draft' || acting.value) return
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
    if (hasPendingJobs.value) load({ quiet: true })
  }, 5000)
})
onBeforeUnmount(() => {
  window.clearInterval(pollTimer)
  if (workbench) workbench.stageActions = null
})
</script>

<template>
  <section class="media-stage">
    <div v-if="!briefHidden" class="media-brief">
      <div class="media-brief-copy">
        <p class="media-eyebrow"><AudioLines :size="15" /> 单知识点媒体验收链路</p>
        <h2>从已确认讲稿生成可发布的课堂媒体</h2>
        <p>选择一个知识点，创建不可变媒体草稿，再按 TTS、字幕与数字人时间轴、PPT manifest、激活的顺序完成处理。</p>
      </div>
      <div class="brief-status" aria-label="媒体服务状态">
        <SfxBadge v-if="providerReady" tone="green">语音服务可用</SfxBadge>
        <SfxBadge v-else-if="providerError" tone="red">语音服务未确认</SfxBadge>
        <SfxBadge v-else tone="amber">正在确认语音服务</SfxBadge>
        <span v-if="provider?.provider_key" class="provider-name">{{ provider.provider_key }}</span>
      </div>
      <SfxButton variant="tertiary" size="sm" class="brief-close" aria-label="折叠介绍" title="折叠介绍" @click="briefHidden = true"><X :size="15" /></SfxButton>
    </div>
    <div v-else class="brief-restore">
      <SfxButton variant="tertiary" size="sm" @click="briefHidden = false"><ChevronDown :size="14" /> 展开介绍</SfxButton>
      <div class="brief-restore-status" aria-label="媒体服务状态">
        <SfxBadge v-if="providerReady" tone="green">语音服务可用</SfxBadge>
        <SfxBadge v-else-if="providerError" tone="red">语音服务未确认</SfxBadge>
        <SfxBadge v-else tone="amber">正在确认语音服务</SfxBadge>
      </div>
    </div>

    <SfxSkeleton v-if="state === 'loading'" :lines="7" block />
    <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />

    <div v-else class="media-workbench">
      <aside class="script-rail" aria-label="可生成媒体的讲稿知识点">
        <header class="rail-header">
          <div><span>讲稿知识点</span><small>{{ scripts.length }} 个可用</small></div>
          <SfxBadge :tone="canGenerate ? 'ink' : 'red'">{{ canGenerate ? '可创建' : '无生成权限' }}</SfxBadge>
        </header>
        <p class="rail-note">只显示已有正文且可绑定 TTS 的讲稿节点。</p>
        <div v-if="scripts.length" class="script-list">
          <SfxButton
            v-for="script in scripts"
            :key="script.script_node_id"
            class="script-item"
            size="sm"
            :variant="selectedScriptId === script.script_node_id ? 'primary' : 'tertiary'"
            :aria-pressed="selectedScriptId === script.script_node_id"
            @click="selectedScriptId = script.script_node_id"
          >
            <span><strong>{{ scriptLabel(script) }}</strong><small>{{ Array.from(script.content || '').length }} 字 · {{ script.locked ? '已锁定讲稿' : '草稿讲稿' }}</small></span>
            <Check v-if="releaseBoundNodeId === script.script_node_db_id" :size="15" />
          </SfxButton>
        </div>
        <div v-else class="rail-empty">
          <Sparkles :size="22" />
          <strong>还没有可用讲稿</strong>
          <p>先在第 03 步生成并确认一个有正文的讲稿知识点。</p>
        </div>
      </aside>

      <main class="media-main">
        <p v-if="notice" class="notice" role="status">{{ notice }}</p>
        <p v-if="error" class="action-error" role="alert"><CircleAlert :size="16" /> {{ error }}</p>
        <p v-if="providerError" class="action-error" role="alert"><CircleAlert :size="16" /> {{ providerError }}</p>

        <template v-if="selectedScript">
          <section class="selected-script" aria-labelledby="selected-script-title">
            <div class="selected-script-heading">
              <span>当前讲稿</span>
              <h3 id="selected-script-title">{{ scriptLabel(selectedScript) }}</h3>
              <p>{{ selectedCharCount }} 字 · {{ selectedByteCount }} UTF-8 字节 · {{ selectedScript.locked ? '已锁定，不会在媒体处理中改写' : '草稿内容将按本次提交冻结' }}</p>
            </div>
            <div class="script-preview">{{ selectedScript.content }}</div>
          </section>

          <section class="release-panel" aria-labelledby="release-title">
            <header class="panel-heading">
              <div>
                <p>工作中的版本</p>
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
                  <label class="confirmation-check"><input v-model="paidTtsConfirmed" type="checkbox" :disabled="!providerReady || !canGenerate" /><span>我确认本次将提交一次语音合成；若当前服务为付费 Provider，将产生相应调用费用。</span></label>
                  <div class="tts-actions">
                    <SfxButton v-if="selectedTtsJob?.status === 'failed'" :disabled="!canSubmitTts" :loading="acting === 'retry-tts'" @click="retryTts">确认并重试一次</SfxButton>
                    <SfxButton v-else :disabled="!canSubmitTts" :loading="acting === 'submit-tts'" @click="submitTts"><Send :size="16" /> 提交语音合成</SfxButton>
                    <small v-if="!providerReady">先等待服务器端语音服务健康检查通过。</small>
                  </div>
                </div>

                <article class="workflow-row" :class="{ complete: hasFrozenCues, active: selectedTtsJob?.status === 'succeeded' && !hasFrozenCues }">
                  <div class="workflow-icon"><Captions :size="18" /></div>
                  <div class="workflow-copy"><span>02 · 字幕与数字人时间轴</span><strong>冻结字幕、说话区间和 PPT 映射快照</strong><p v-if="hasFrozenCues">已生成 release-scoped subtitle-manifest/v1 与 avatar-cues/v1。</p><p v-else-if="cueJob">{{ jobStatusLabel(cueJob) }} · {{ cueJob.error_message_safe || '不再调用 TTS Provider' }}</p><p v-else>需要成功 TTS；缺少音素时仅生成字级/字幕驱动的通用说话状态，不宣称精确口型。</p></div>
                  <SfxBadge :tone="hasFrozenCues ? 'green' : cueJob ? jobTone(cueJob) : 'neutral'">{{ hasFrozenCues ? '已冻结' : cueJob ? jobStatusLabel(cueJob) : '等待 TTS' }}</SfxBadge>
                </article>
                <div v-if="selectedTtsJob?.status === 'succeeded' && !hasFrozenCues && (!cueJob || cueJob.status === 'failed')" class="workflow-action"><SfxButton :disabled="!canGenerate" :loading="acting === 'freeze-cues'" @click="freezeCues">冻结字幕与数字人时间轴</SfxButton></div>

                <article class="workflow-row" :class="{ complete: hasPptManifest, active: hasFrozenCues && !hasPptManifest }">
                  <div class="workflow-icon"><FileImage :size="18" /></div>
                  <div class="workflow-copy"><span>03 · PPT manifest</span><strong>冻结学生端播放所需的 PPT 页图清单</strong><p v-if="hasPptManifest">PPT manifest 已绑定到此媒体草稿。</p><p v-else>如果第 04 步尚无可渲染 PPT/PDF 源文件，本步骤会明确返回阻塞原因；可先回到映射页处理。</p></div>
                  <SfxBadge :tone="hasPptManifest ? 'green' : 'amber'">{{ hasPptManifest ? '已冻结' : '可选但建议完成' }}</SfxBadge>
                </article>
                <div v-if="hasFrozenCues && !hasPptManifest" class="workflow-action"><SfxButton variant="secondary" :disabled="!canGenerate" :loading="acting === 'ppt-manifest'" @click="createPptManifest">生成 PPT manifest</SfxButton></div>

                <article class="workflow-row" :class="{ complete: workingRelease.status === 'active', active: hasFrozenCues && workingRelease.status === 'draft' }">
                  <div class="workflow-icon"><Check :size="18" /></div>
                  <div class="workflow-copy"><span>04 · 激活并固化到课程发布</span><strong>激活媒体版本，再重新正式发布课程</strong><p v-if="workingRelease.status === 'active'">媒体已激活；课程正式发布时会把它写入不可变媒体快照。</p><p v-else>激活不会自动改写学生当前课程版本。完成激活后仍需到第 07 步重新正式发布。</p></div>
                  <SfxBadge :tone="workingRelease.status === 'active' ? 'green' : 'amber'">{{ workingRelease.status === 'active' ? '已激活' : '等待激活' }}</SfxBadge>
                </article>
                <div v-if="workingRelease.status === 'draft'" class="workflow-action"><SfxButton :disabled="!canPublish || !hasFrozenCues" :loading="acting === 'activate'" @click="activateRelease">激活媒体版本</SfxButton></div>
                <div v-else-if="workingRelease.status === 'active'" class="workflow-action"><SfxButton @click="goToRelease">前往正式发布</SfxButton></div>
              </div>
            </template>
          </section>

          <section class="task-panel" aria-labelledby="task-title">
            <header class="panel-heading">
              <div><p>任务留痕</p><h3 id="task-title">媒体任务队列</h3></div>
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

          <aside class="scope-note"><CircleAlert :size="17" /><div><strong>当前首版边界</strong><p>此工作台完成的是「一个知识点 → 一段音频 → Cue/PPT → 媒体版本」的受控验收链路。全课程多知识点连续音频播放列表尚未实现，不能把单知识点草稿当作整门课程媒体。</p></div></aside>
        </template>
        <div v-else class="main-empty"><Sparkles :size="28" /><strong>先生成讲稿，再创建课堂媒体</strong><p>媒体中心只处理已确认的讲稿节点，因此不会凭空生成或猜测教学内容。</p></div>
      </main>
    </div>
  </section>
</template>

<style scoped>
.media-stage{height:100%;min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr);gap:var(--space-4);overflow:hidden}
.media-brief{position:relative;display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-6);padding:var(--space-4) var(--space-5);border:1px solid var(--border-default);border-radius:var(--radius-lg);background:var(--surface-cool);flex-shrink:0}.brief-close{position:absolute;top:var(--space-2);right:var(--space-2)}.brief-restore{display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);padding:var(--space-2) var(--space-3);border:1px solid var(--border-default);border-radius:var(--radius-md);background:var(--surface-cool);flex-shrink:0}.brief-restore-status{display:flex;align-items:center;gap:var(--space-2)}.media-brief-copy{min-width:0}.media-eyebrow{display:flex;align-items:center;gap:var(--space-1);margin:0;color:var(--ink-700);font-size:var(--caption-size);font-weight:650;letter-spacing:.06em}.media-brief h2{margin:var(--space-1) 0 0;color:var(--text-primary);font-size:var(--title-3-size);line-height:var(--title-3-line)}.media-brief p:not(.media-eyebrow){max-width:680px;margin:var(--space-1) 0 0;color:var(--text-secondary);font-size:var(--ui-sm-size);line-height:1.55}.brief-status{display:grid;justify-items:end;gap:var(--space-1);flex-shrink:0}.provider-name{max-width:180px;overflow:hidden;color:var(--text-muted);font-family:var(--font-mono);font-size:11px;text-overflow:ellipsis;white-space:nowrap}
.media-workbench{display:grid;grid-template-columns:272px minmax(0,1fr);grid-template-rows:minmax(0,1fr);min-height:0;border:1px solid var(--border-default);border-radius:var(--radius-lg);overflow:hidden;background:var(--surface-canvas)}
.script-rail{display:flex;flex-direction:column;min-height:0;background:var(--surface-panel);border-right:1px solid var(--border-default)}.rail-header{display:flex;align-items:center;justify-content:space-between;gap:var(--space-2);padding:var(--space-3);border-bottom:1px solid var(--border-subtle)}.rail-header>div{display:grid;gap:1px}.rail-header span{color:var(--text-primary);font-size:var(--ui-md-size);font-weight:650}.rail-header small,.rail-note{color:var(--text-muted);font-size:var(--caption-size)}.rail-note{margin:0;padding:var(--space-2) var(--space-3);border-bottom:1px solid var(--border-subtle);line-height:1.45}.script-list{display:grid;align-content:start;gap:var(--space-1);min-height:0;overflow-y:auto;padding:var(--space-2)}.script-item{width:100%;min-height:54px;justify-content:space-between;text-align:left}.script-item>span{display:grid;min-width:0;gap:2px}.script-item strong,.script-item small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.script-item strong{font-size:var(--ui-sm-size)}.script-item small{font-size:11px;opacity:.8}.rail-empty{display:grid;justify-items:center;gap:var(--space-2);margin:auto;padding:var(--space-6);color:var(--text-muted);text-align:center}.rail-empty strong{color:var(--text-primary);font-size:var(--ui-md-size)}.rail-empty p{margin:0;font-size:var(--caption-size);line-height:1.5}
.media-main{display:flex;flex-direction:column;gap:var(--space-4);min-width:0;min-height:0;overflow-y:auto;padding:var(--space-4) var(--space-5)}.notice,.action-error{display:flex;align-items:flex-start;gap:var(--space-2);margin:0;padding:var(--space-3);border-radius:var(--radius-md);font-size:var(--ui-sm-size);line-height:1.5}.notice{border:1px solid var(--ink-300);background:var(--ink-100);color:var(--ink-700)}.action-error{border:1px solid var(--red-300);background:var(--red-100);color:var(--red-700)}
.selected-script{display:grid;grid-template-columns:minmax(210px,.72fr) minmax(0,1.28fr);gap:var(--space-4);padding:var(--space-4);border-left:3px solid var(--ink-500);background:var(--surface-cool);max-height:320px;min-height:160px;overflow:hidden}.selected-script-heading{display:grid;align-content:start;gap:var(--space-1);overflow-y:auto;min-height:0}.selected-script-heading>span,.panel-heading p,.workflow-copy>span{color:var(--text-muted);font-size:var(--caption-size);font-weight:600;letter-spacing:.04em}.selected-script-heading h3{margin:0;color:var(--text-primary);font-size:var(--title-3-size);line-height:var(--title-3-line)}.selected-script-heading p{margin:0;color:var(--text-secondary);font-size:var(--caption-size);line-height:1.5}.script-preview{max-height:100%;overflow-y:auto;color:var(--text-primary);font-size:var(--ui-sm-size);line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere}
.release-panel,.task-panel{border:1px solid var(--border-default);border-radius:var(--radius-md);background:var(--surface-panel);overflow:hidden}.release-panel{max-width:760px;width:100%;margin-inline:auto}.panel-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-3);padding:var(--space-3) var(--space-4);border-bottom:1px solid var(--border-subtle)}.panel-heading p{margin:0}.panel-heading h3{margin:2px 0 0;color:var(--text-primary);font-size:var(--ui-md-size)}.release-picker{display:flex;gap:var(--space-1);overflow-x:auto;padding:var(--space-2) var(--space-3);border-bottom:1px solid var(--border-subtle)}.release-empty{display:flex;align-items:center;gap:var(--space-3);padding:var(--space-5);color:var(--text-muted)}.release-empty>div{display:grid;gap:var(--space-1);min-width:0;flex:1}.release-empty strong{color:var(--text-primary);font-size:var(--ui-md-size)}.release-empty p{margin:0;font-size:var(--ui-sm-size);line-height:1.5}.binding-warning{display:grid;grid-template-columns:20px minmax(0,1fr) auto;align-items:start;gap:var(--space-2);padding:var(--space-4);background:var(--amber-100);color:var(--amber-700)}.binding-warning div{display:grid;gap:var(--space-1)}.binding-warning strong{color:var(--text-primary);font-size:var(--ui-md-size)}.binding-warning p{margin:0;font-size:var(--ui-sm-size);line-height:1.5}
.workflow-list{display:grid}.workflow-row{display:grid;grid-template-columns:34px minmax(0,1fr) auto;gap:var(--space-3);align-items:start;padding:var(--space-4);border-bottom:1px solid var(--border-subtle)}.workflow-row.active{background:var(--ink-100)}.workflow-row.complete{background:var(--green-100)}.workflow-icon{display:grid;place-items:center;width:32px;height:32px;border-radius:var(--radius-full);background:var(--surface-cool);color:var(--ink-700)}.workflow-row.complete .workflow-icon{background:var(--surface-panel);color:var(--green-700)}.workflow-copy{display:grid;gap:2px;min-width:0}.workflow-copy strong{color:var(--text-primary);font-size:var(--ui-md-size);line-height:1.45}.workflow-copy p{margin:0;color:var(--text-secondary);font-size:var(--ui-sm-size);line-height:1.5}.tts-confirmation,.workflow-action{margin:0 var(--space-4) var(--space-4);padding:var(--space-3);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);background:var(--surface-cool)}.confirmation-check{display:flex;align-items:flex-start;gap:var(--space-2);color:var(--text-secondary);font-size:var(--ui-sm-size);line-height:1.5}.confirmation-check input{width:16px;height:16px;margin:2px 0 0;accent-color:var(--ink-700);flex-shrink:0}.tts-actions{display:flex;align-items:center;gap:var(--space-3);margin-top:var(--space-3)}.tts-actions small{color:var(--text-muted);font-size:var(--caption-size)}.workflow-action{display:flex;justify-content:flex-end;padding:0;border:0;background:transparent}
.task-list{display:grid}.task-row{display:grid;grid-template-columns:minmax(0,1fr) auto 150px;gap:var(--space-3);align-items:center;padding:var(--space-3) var(--space-4);border-bottom:1px solid var(--border-subtle)}.task-row:last-child{border-bottom:0}.task-row>div{display:grid;gap:2px;min-width:0}.task-row strong,.task-row span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.task-row strong{color:var(--text-primary);font-size:var(--ui-sm-size)}.task-row span{color:var(--text-muted);font-size:var(--caption-size)}.task-time{justify-self:end}.task-row .task-error,.task-row .task-output{grid-column:1/-1;margin:0;font-size:var(--caption-size);line-height:1.45}.task-error{color:var(--red-700)}.task-output{color:var(--green-700)}.task-empty{margin:0;padding:var(--space-5);color:var(--text-muted);font-size:var(--ui-sm-size);text-align:center}.scope-note{display:grid;grid-template-columns:20px minmax(0,1fr);gap:var(--space-2);padding:var(--space-3);border:1px solid var(--amber-300);border-radius:var(--radius-md);background:var(--amber-100);color:var(--amber-700)}.scope-note strong{color:var(--text-primary);font-size:var(--ui-sm-size)}.scope-note p{margin:var(--space-1) 0 0;color:var(--text-secondary);font-size:var(--caption-size);line-height:1.55}.main-empty{display:grid;place-items:center;align-content:center;gap:var(--space-2);min-height:300px;color:var(--text-muted);text-align:center}.main-empty strong{color:var(--text-primary);font-size:var(--title-3-size)}.main-empty p{max-width:380px;margin:0;font-size:var(--ui-sm-size);line-height:1.5}
@media(max-width:960px){.media-brief{align-items:stretch;flex-direction:column}.brief-status{justify-items:start}.media-workbench{grid-template-columns:220px minmax(0,1fr)}.selected-script{grid-template-columns:1fr;max-height:none}.release-panel{max-width:none}.task-row{grid-template-columns:minmax(0,1fr) auto}.task-time{display:none}}
@media(max-width:700px){.media-stage{height:auto;overflow:visible}.media-workbench{grid-template-columns:1fr;grid-template-rows:auto auto;overflow:visible}.script-rail{max-height:260px;border-right:0;border-bottom:1px solid var(--border-default)}.media-main{overflow:visible;padding:var(--space-3)}.selected-script{max-height:none;overflow:visible}.selected-script-heading{overflow:visible}.workflow-row{grid-template-columns:34px minmax(0,1fr)}.workflow-row>.sfx-badge{grid-column:2}.binding-warning{grid-template-columns:20px minmax(0,1fr)}.binding-warning .sfx-btn{grid-column:2;justify-self:start}.release-empty{align-items:flex-start;flex-wrap:wrap}.release-empty .sfx-btn{margin-left:35px}.tts-actions{align-items:flex-start;flex-direction:column}.media-brief{padding:var(--space-4)}.task-row{grid-template-columns:minmax(0,1fr) auto}}
</style>
