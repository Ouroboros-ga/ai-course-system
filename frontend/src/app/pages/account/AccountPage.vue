<script setup>
import { computed, onMounted, ref } from 'vue'
import { AudioLines, Sparkles, Upload, UserRound, Video } from 'lucide-vue-next'
import {
  confirmAvatarSourceMedia,
  createAvatarPreparationJob,
  createAvatarProfile,
  listAvatarPreparationJobs,
  listAvatarSourceMedia,
  listMyAvatarProfiles,
  requestAvatarSourceUploadIntent,
  uploadAvatarSourceMedia,
} from '@/api/avatar.js'
import { useCounterStore } from '@/stores/counter.js'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import SfxError from '@/app/ui/SfxError.vue'
import SfxField from '@/app/ui/SfxField.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'

const counter = useCounterStore()
const state = ref('loading')
const profiles = ref([])
const sourceMedia = ref({})
const preparationJobs = ref({})
const selectedFiles = ref({})
const uploadProgress = ref({})
const busy = ref({})
const displayName = ref('')
const notes = ref('')
const confirmedConsent = ref(false)
const creating = ref(false)
const error = ref('')
const canCreate = computed(() => displayName.value.trim().length > 0 && confirmedConsent.value && !creating.value)

function profileSources(profileId) { return sourceMedia.value[profileId] ?? [] }
function profileJobs(profileId) { return preparationJobs.value[profileId] ?? [] }
function mediaFor(profileId, kind) {
  return profileSources(profileId).find((item) => item.media_type === kind && item.upload_status === 'verified')
}
function selectedKey(profileId, kind) { return `${profileId}:${kind}` }
function setBusy(key, value) { busy.value = { ...busy.value, [key]: value } }
function isBusy(key) { return Boolean(busy.value[key]) }

async function loadProfileAssets(profileId) {
  const [media, jobs] = await Promise.all([
    listAvatarSourceMedia(profileId),
    listAvatarPreparationJobs(profileId),
  ])
  sourceMedia.value = { ...sourceMedia.value, [profileId]: Array.isArray(media?.items) ? media.items : [] }
  preparationJobs.value = { ...preparationJobs.value, [profileId]: Array.isArray(jobs?.items) ? jobs.items : [] }
}

async function load() {
  state.value = 'loading'
  try {
    const data = await listMyAvatarProfiles()
    profiles.value = Array.isArray(data?.items) ? data.items : []
    await Promise.all(profiles.value.map((profile) => loadProfileAssets(profile.avatar_id)))
    state.value = profiles.value.length ? 'ready' : 'empty'
  } catch (caught) {
    error.value = caught?.response?.data?.detail || caught?.message || ''
    state.value = 'error'
  }
}

async function createProfile() {
  if (!canCreate.value) return
  creating.value = true
  error.value = ''
  try {
    const data = await createAvatarProfile({
      display_name: displayName.value.trim(),
      provider_key: 'fake',
      notes: notes.value.trim(),
      consent_text: '我确认拥有上传肖像和声音素材的授权，并同意仅用于本人课程的数字人预设。',
    })
    profiles.value.unshift(data)
    await loadProfileAssets(data.avatar_id)
    displayName.value = ''
    notes.value = ''
    confirmedConsent.value = false
    state.value = 'ready'
  } catch (caught) {
    error.value = caught?.response?.data?.detail || caught?.message || '无法创建数字人预设。'
  } finally { creating.value = false }
}

function selectSource(profileId, kind, event) {
  const file = event.target.files?.[0] ?? null
  selectedFiles.value = { ...selectedFiles.value, [selectedKey(profileId, kind)]: file }
}

async function uploadSource(profile, kind) {
  const key = selectedKey(profile.avatar_id, kind)
  const file = selectedFiles.value[key]
  if (!file || isBusy(key)) return
  setBusy(key, true)
  error.value = ''
  uploadProgress.value = { ...uploadProgress.value, [key]: 0 }
  try {
    const intentResponse = await requestAvatarSourceUploadIntent(profile.avatar_id, {
      media_type: kind,
      mime_type: file.type || 'application/octet-stream',
      size_bytes: file.size,
    })
    const intent = intentResponse?.upload_intent
    const source = intentResponse?.source_media
    if (!intent?.upload_url || !source?.source_media_id) throw new Error('服务器没有返回有效的受控上传地址。')
    await uploadAvatarSourceMedia(intent.upload_url, file, intent.headers ?? {}, {
      method: intent.method,
      fields: intent.fields,
      onUploadProgress: (event) => {
        if (event.total) uploadProgress.value = { ...uploadProgress.value, [key]: Math.round((event.loaded / event.total) * 100) }
      },
    })
    await confirmAvatarSourceMedia(profile.avatar_id, source.source_media_id)
    selectedFiles.value = { ...selectedFiles.value, [key]: null }
    uploadProgress.value = { ...uploadProgress.value, [key]: 100 }
    await loadProfileAssets(profile.avatar_id)
  } catch (caught) {
    error.value = caught?.response?.data?.detail || caught?.message || '素材上传或服务端校验失败。'
  } finally { setBusy(key, false) }
}

async function prepare(profile) {
  const key = `${profile.avatar_id}:prepare`
  if (isBusy(key) || !mediaFor(profile.avatar_id, 'portrait_video') || !mediaFor(profile.avatar_id, 'voice_sample')) return
  setBusy(key, true)
  error.value = ''
  try {
    await createAvatarPreparationJob(profile.avatar_id, { idempotency_key: `profile-${profile.avatar_id}-assets` })
    await loadProfileAssets(profile.avatar_id)
  } catch (caught) {
    error.value = caught?.response?.data?.detail || caught?.message || '无法创建预处理任务。'
  } finally { setBusy(key, false) }
}

function latestJob(profileId) { return profileJobs(profileId)[0] }
function statusTone(status) { return status === 'ready' || status === 'succeeded' ? 'green' : status === 'failed' ? 'red' : 'amber' }
function readableStatus(status) {
  return ({ verified: '已校验', uploaded: '待校验', pending: '等待处理', running: '预处理中', succeeded: '已完成', failed: '处理失败', ready: '可用' })[status] ?? status
}

onMounted(load)
</script>

<template>
  <div class="sfx-page sfx-page--narrow">
    <header class="sfx-page-header"><div><h1 class="sfx-t-title1"><UserRound :size="25" /> 个人中心</h1><p class="sfx-t-ui sfx-t-secondary sfx-page-header-sub">账户信息与专属数字人预设。素材上传、校验和预处理均由独立任务完成。</p></div></header>
    <section class="sfx-panel account-summary"><span class="sfx-t-ui">账户</span><strong>{{ counter.userData.username || '—' }}</strong><SfxBadge tone="ink">{{ counter.userData.role || 'member' }}</SfxBadge></section>
    <section class="sfx-panel"><h2 class="sfx-panel-title"><Sparkles :size="18" /> 新建数字人预设</h2><p class="sfx-t-ui sfx-t-secondary">先建立有授权的预设记录；随后上传本人肖像视频和声音样本。原始素材不会提供给课程学生下载。</p><SfxField label="预设名称"><input v-model="displayName" class="sfx-input" placeholder="例如：李老师课程讲解" /></SfxField><SfxField label="说明（可选）"><textarea v-model="notes" class="sfx-textarea" rows="3" placeholder="适用课程或讲解风格" /></SfxField><label class="consent"><input v-model="confirmedConsent" type="checkbox" /> 我确认拥有上传肖像、视频与声音素材的授权。</label><SfxButton variant="primary" :disabled="!canCreate" :loading="creating" @click="createProfile">创建预设</SfxButton><p v-if="error" class="account-error" role="alert">{{ error }}</p></section>
    <section><h2 class="sfx-t-title2">我的数字人预设</h2><SfxSkeleton v-if="state === 'loading'" :lines="3" block /><SfxError v-else-if="state === 'error'" :description="error || '无法读取预设。'" @retry="load" /><SfxEmpty v-else-if="state === 'empty'" title="还没有数字人预设" description="创建预设后，上传肖像视频和声音样本，才能创建服务端预处理任务。" /><div v-else class="profile-list"><article v-for="profile in profiles" :key="profile.avatar_id" class="sfx-panel profile-card"><div class="profile-head"><div><h3 class="sfx-t-title3">{{ profile.display_name }}</h3><p class="sfx-t-caption sfx-t-secondary">{{ profile.avatar_id }}</p></div><SfxBadge :tone="statusTone(profile.status)">{{ readableStatus(profile.status) }}</SfxBadge></div><p class="sfx-t-ui sfx-t-secondary">{{ profile.current_asset_package_id ? '资产包已就绪，可在本人课程中绑定到媒体发布版本。' : '上传并校验两类素材后，创建后台预处理任务。' }}</p><div class="source-grid"><section class="source-card"><h4><Video :size="17" /> 肖像视频</h4><SfxBadge :tone="mediaFor(profile.avatar_id, 'portrait_video') ? 'green' : 'amber'">{{ mediaFor(profile.avatar_id, 'portrait_video') ? '已校验' : '待上传' }}</SfxBadge><input :aria-label="`${profile.display_name} 的肖像视频`" type="file" accept="video/mp4,video/webm,video/quicktime" :disabled="isBusy(selectedKey(profile.avatar_id, 'portrait_video'))" @change="selectSource(profile.avatar_id, 'portrait_video', $event)" /><p v-if="selectedFiles[selectedKey(profile.avatar_id, 'portrait_video')]" class="sfx-t-caption">{{ selectedFiles[selectedKey(profile.avatar_id, 'portrait_video')].name }}</p><progress v-if="isBusy(selectedKey(profile.avatar_id, 'portrait_video'))" :value="uploadProgress[selectedKey(profile.avatar_id, 'portrait_video')] ?? 0" max="100" /><SfxButton size="sm" variant="secondary" :disabled="!selectedFiles[selectedKey(profile.avatar_id, 'portrait_video')]" :loading="isBusy(selectedKey(profile.avatar_id, 'portrait_video'))" @click="uploadSource(profile, 'portrait_video')"><Upload :size="15" /> 上传并校验</SfxButton></section><section class="source-card"><h4><AudioLines :size="17" /> 声音样本</h4><SfxBadge :tone="mediaFor(profile.avatar_id, 'voice_sample') ? 'green' : 'amber'">{{ mediaFor(profile.avatar_id, 'voice_sample') ? '已校验' : '待上传' }}</SfxBadge><input :aria-label="`${profile.display_name} 的声音样本`" type="file" accept="audio/mpeg,audio/wav,audio/x-wav,audio/mp4,audio/ogg" :disabled="isBusy(selectedKey(profile.avatar_id, 'voice_sample'))" @change="selectSource(profile.avatar_id, 'voice_sample', $event)" /><p v-if="selectedFiles[selectedKey(profile.avatar_id, 'voice_sample')]" class="sfx-t-caption">{{ selectedFiles[selectedKey(profile.avatar_id, 'voice_sample')].name }}</p><progress v-if="isBusy(selectedKey(profile.avatar_id, 'voice_sample'))" :value="uploadProgress[selectedKey(profile.avatar_id, 'voice_sample')] ?? 0" max="100" /><SfxButton size="sm" variant="secondary" :disabled="!selectedFiles[selectedKey(profile.avatar_id, 'voice_sample')]" :loading="isBusy(selectedKey(profile.avatar_id, 'voice_sample'))" @click="uploadSource(profile, 'voice_sample')"><Upload :size="15" /> 上传并校验</SfxButton></section></div><div class="prepare-row"><div><strong class="sfx-t-ui">服务端预处理</strong><p class="sfx-t-caption sfx-t-secondary">{{ latestJob(profile.avatar_id) ? `最近任务：${readableStatus(latestJob(profile.avatar_id).status)}（${latestJob(profile.avatar_id).task_id}）` : '校验两类素材后可创建任务；任务写入任务中心，离开此页不会中断。' }}</p></div><SfxButton variant="primary" :disabled="!mediaFor(profile.avatar_id, 'portrait_video') || !mediaFor(profile.avatar_id, 'voice_sample')" :loading="isBusy(`${profile.avatar_id}:prepare`)" @click="prepare(profile)">创建预处理任务</SfxButton></div></article></div></section>
  </div>
</template>

<style scoped>
.sfx-page-header h1, .sfx-panel-title, .source-card h4 { display: flex; align-items: center; gap: var(--space-2); }
.account-summary, .profile-head, .prepare-row { display: flex; align-items: center; gap: var(--space-3); }
.profile-head, .prepare-row { justify-content: space-between; }
.sfx-panel { display: flex; flex-direction: column; align-items: flex-start; gap: var(--space-3); margin-bottom: var(--space-6); }
.sfx-input, .sfx-textarea { width: 100%; }
.consent { display: flex; gap: var(--space-2); color: var(--text-secondary); font-size: var(--ui-sm-size); }
.profile-list { display: grid; gap: var(--space-3); margin-top: var(--space-3); }
.profile-card { margin: 0; }
.source-grid { width: 100%; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.source-card { display: grid; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--border-default); border-radius: var(--radius-md); }
.source-card h4 { margin: 0; }
.source-card progress { width: 100%; }
.prepare-row { width: 100%; border-top: 1px solid var(--border-subtle); padding-top: var(--space-3); }
.account-error { color: var(--red-700); }
@media (max-width: 640px) { .source-grid { grid-template-columns: 1fr; } .prepare-row { align-items: flex-start; flex-direction: column; } }
</style>
