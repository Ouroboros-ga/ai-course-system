/**
 * BuildMediaPage 的状态与动作组合式函数。
 * 页面壳与各面板组件通过 inject('mediaBuild') 共享同一个实例，
 * 避免把一个 900 行页面里的状态、computed 与方法重复下发到子组件。
 */
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
import { apiErrorMessage } from '@/utils/apiErrorMessage.js'
import { withAccessToken } from '@/features/student-learning/adapters/playerWorkspaceAdapter.js'

export function useMediaBuild() {
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
    const previewNodeLabel = ref('')
    const lastAutoPreviewId = ref('')

    // 试听播放器与预览面板由子组件持有 DOM，通过注册回调打通：
    // 组合式函数只负责"触发播放/滚动"，不直接持有元素引用。
    let previewAudioEl = null
    let previewPanelScrollCb = null
    function registerPreviewAudio(el) { previewAudioEl = el }
    function playPreviewAudio() { return previewAudioEl?.play?.() ?? Promise.resolve() }
    function registerPreviewPanelScroll(cb) { previewPanelScrollCb = cb }
    function scrollPreviewIntoView() { previewPanelScrollCb?.() }

    const allowed = computed(() => courseContext?.allowed?.value ?? {})
    const canGenerate = computed(() => Boolean(allowed.value['course.media.generate']))
    const canPublish = computed(() => Boolean(allowed.value['course.publish']))
    const selectedScript = computed(() => scripts.value.find((item) => item.script_node_id === selectedScriptId.value) ?? null)
    const selectedNodeDbId = computed(() => Number(selectedScript.value?.script_node_db_id) || null)
    const workingRelease = computed(() => releaseDetail.value ?? releases.value.find((item) => item.release_id === selectedReleaseId.value) ?? null)
    const provider = computed(() => providerHealth.value?.tts ?? null)
    const providerKey = computed(() => provider.value?.provider_key || '')
    const providerDisplayName = computed(() => provider.value?.display_name || provider.value?.effective_provider || '未配置')
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
    const pptManifestJob = computed(() => jobs.value.find((job) => (
        job.job_type === 'ppt_manifest' && job.media_release_id === workingRelease.value?.release_id
    )) ?? null)
    const pptManifestInFlight = computed(() => ['pending', 'running'].includes(pptManifestJob.value?.status))
    const pptManifestProgress = computed(() => pptManifestJob.value?.output_metadata?.page_progress ?? null)
    const isPlaylistRelease = computed(() => Boolean(workingRelease.value?.release_metadata?.audio_playlist_mode))
    const hasFrozenPlaylist = computed(() => Boolean(workingRelease.value?.audio_playlist_object_key && workingRelease.value?.audio_playlist_sha256))
    const canActivateWorkingRelease = computed(() => {
        if (!workingRelease.value || workingRelease.value.status !== 'draft' || !hasPptManifest.value) return false
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
    const canBuildPptManifest = computed(() => isPlaylistRelease.value ? batchReady.value : hasFrozenCues.value)

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
        if (job?.job_type === 'ppt_manifest') return 'PPT 页面清单'
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
        const item = findBatchItemForScript(script)
        return item?.audio_object_key ? item : null
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
            playPreviewAudio().catch(() => {
                notice.value = '草稿音频已准备好；浏览器阻止自动播放时，请点击播放器的播放键。'
            })
            scrollPreviewIntoView()
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
            playPreviewAudio().catch(() => { })
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
        if (!canGenerate.value || !workingRelease.value || acting.value || pptManifestInFlight.value) return
        acting.value = 'ppt-manifest'
        error.value = ''
        notice.value = ''
        try {
            const result = await buildPptManifest(courseId.value, workingRelease.value.release_id)
            if (result.async) {
                jobs.value = [result, ...jobs.value.filter((item) => item.job_id !== result.job_id)]
                notice.value = 'PPT manifest 已转入后台：将复用映射页图，仅在发现缺页时补渲染。页面会每 5 秒更新进度。'
            } else {
                notice.value = 'PPT manifest 已存在，无需重复渲染。'
                await refreshReleaseDetail()
            }
        } catch (caught) {
            error.value = apiErrorMessage(caught, 'PPT manifest 未提交。请先回到第 04 步确认 PPT 源文件和映射。')
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

    return {
        // 上下文
        route, router, courseId, workbench, courseContext,
        // 状态
        state, error, providerError, notice, scripts, jobs, releases,
        releaseDetail, providerHealth, presetCatalog,
        selectedVoicePresetId, selectedVoicePresetVersion,
        selectedAvatarPresetId, selectedAvatarPresetVersion,
        selectedScriptId, selectedReleaseId, paidTtsConfirmed, acting, refreshing,
        batchNodeIds, batchPlan, batchState,
        previewItem, previewPlayback, previewNodeLabel, lastAutoPreviewId,
        // computed
        allowed, canGenerate, canPublish, selectedScript, selectedNodeDbId,
        workingRelease, provider, providerKey, providerDisplayName, providerReady,
        providerNeedsConfirmation, providerIsDemo, selectedVoicePreset, selectedAvatarPreset,
        selectedCharCount, selectedByteCount,
        releaseTtsJobs, releaseTtsJob, selectedTtsJob, releaseBoundNodeId,
        releaseMatchesSelection, boundScript, cueJob, hasFrozenCues, hasPptManifest,
        pptManifestJob, pptManifestInFlight, pptManifestProgress, isPlaylistRelease,
        hasFrozenPlaylist, canActivateWorkingRelease, hasPendingJobs, activeBatchId,
        batchItems, canCreateDraft, canSubmitTts, batchSelectedScripts, selectedBatchItem,
        canPlanBatch, batchPlanMatchesSelections, canConfirmBatch, batchReady,
        releaseCueAssetsReady, canBuildPptManifest,
        // 方法
        jobTone, releaseTone, releaseStatusLabel, jobStatusLabel, batchStatusLabel,
        batchItemStatusLabel, scriptLabel, sameMediaNode, findBatchItemForScript,
        findScriptForBatchItem, jobLabel, formatDate,
        makeTtsIdempotencyKey, makeCueIdempotencyKey, chooseDefaultRelease,
        refreshReleaseDetail, refreshBatchState, load, toggleBatchNode,
        scriptItemAudio, withPreviewAccessToken,
        createBatchPlan, confirmBatch, applyPreview, fetchPreview, previewBatchItem,
        freezeBatchPlaylist, selectRelease, createDraft, ttsPayload, submitTts,
        retryTts, freezeCues, createPptManifest, activateRelease, goToRelease,
        // DOM 桥接
        registerPreviewAudio, playPreviewAudio, registerPreviewPanelScroll, scrollPreviewIntoView,
    }
}
