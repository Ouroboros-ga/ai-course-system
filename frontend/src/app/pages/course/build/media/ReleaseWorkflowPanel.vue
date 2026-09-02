<script setup>
import { inject } from 'vue'
import { Captions, Check, CircleAlert, FileImage, Send, Volume2 } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const mediaBuild = inject('mediaBuild')
const {
    releases, workingRelease, releaseTone, releaseStatusLabel, selectRelease,
    canCreateDraft, createDraft, releaseMatchesSelection, boundScript, scriptLabel,
    selectedTtsJob, jobStatusLabel, isPlaylistRelease, jobTone,
    providerNeedsConfirmation, providerIsDemo, canSubmitTts, retryTts, submitTts, providerReady,
    releaseCueAssetsReady, cueJob, hasFrozenCues, freezeCues, batchReady, paidTtsConfirmed,
    hasPptManifest, pptManifestInFlight, pptManifestProgress, pptManifestJob,
    canBuildPptManifest, createPptManifest, hasFrozenPlaylist, freezeBatchPlaylist,
    canActivateWorkingRelease, activateRelease, canPublish, goToRelease, canGenerate, acting,
} = mediaBuild

// 长文案提取为常量，避免模板内插值字符串被自动格式化断行
const TTS_FALLBACK = '不再调用 TTS Provider'
const PPT_FAILED_FALLBACK = 'PPT manifest 后台任务失败，请检查任务记录后重试。'
function workingReleaseTitle() {
    const r = workingRelease.value
    return r ? (r.label || `媒体版本 ${r.version_number}`) : '尚未创建媒体草稿'
}
</script>

<template>
    <section class="release-panel" aria-labelledby="release-title">
        <header class="panel-heading">
            <div>
                <p>媒体版本与处理流程</p>
                <h3 id="release-title">{{ workingReleaseTitle() }}</h3>
            </div>
            <SfxBadge v-if="workingRelease" :tone="releaseTone(workingRelease)">{{ releaseStatusLabel(workingRelease) }}
            </SfxBadge>
        </header>

        <div v-if="releases.length" class="release-picker" aria-label="课程媒体版本">
            <SfxButton v-for="release in releases" :key="release.release_id" size="sm"
                :variant="release.release_id === workingRelease?.release_id ? 'secondary' : 'tertiary'"
                @click="selectRelease(release)">v{{ release.version_number }} · {{ releaseStatusLabel(release) }}
            </SfxButton>
        </div>

        <div v-if="!workingRelease" class="release-empty">
            <FileImage :size="23" />
            <div><strong>先创建一个媒体验收草稿</strong>
                <p>草稿不会影响当前已激活或学生可见的媒体版本。</p>
            </div>
            <SfxButton size="sm" :disabled="!canCreateDraft" :loading="acting === 'create-release'"
                @click="createDraft">创建媒体验收草稿</SfxButton>
        </div>

        <template v-else>
            <div v-if="!releaseMatchesSelection" class="binding-warning">
                <CircleAlert :size="18" />
                <div><strong>此草稿已绑定其他知识点</strong>
                    <p>它正在处理「{{ scriptLabel(boundScript) }}」。一个草稿当前只支持一段知识点音频；为当前讲稿请新建草稿。</p>
                </div>
                <SfxButton size="sm" :disabled="!canCreateDraft" :loading="acting === 'create-release'"
                    @click="createDraft">新建草稿</SfxButton>
            </div>

            <div v-else class="workflow-list">
                <article class="workflow-row"
                    :class="{ complete: Boolean(selectedTtsJob?.status === 'succeeded'), active: !selectedTtsJob }">
                    <div class="workflow-icon">
                        <Volume2 :size="18" />
                    </div>
                    <div class="workflow-copy"><span>01 · 语音合成</span><strong>将当前讲稿提交给已配置的服务器端音色</strong>
                        <p v-if="selectedTtsJob">{{ jobStatusLabel(selectedTtsJob) }} · {{
                            selectedTtsJob.output_metadata?.cache_hit ? '命中已有音频缓存' : selectedTtsJob.error_message_safe
                                || '任务状态会自动刷新' }}</p>
                        <p v-else-if="isPlaylistRelease">该知识点不在本批已确认的节点内；请在上方批量面板勾选后重新核算并确认。</p>
                        <p v-else>提交前需教师明确确认；页面不会读取或展示任何密钥、音色 ID。</p>
                    </div>
                    <SfxBadge v-if="selectedTtsJob" :tone="jobTone(selectedTtsJob)">{{ jobStatusLabel(selectedTtsJob) }}
                    </SfxBadge>
                </article>

                <div v-if="!isPlaylistRelease && (!selectedTtsJob || selectedTtsJob.status === 'failed')"
                    class="tts-confirmation">
                    <label v-if="providerNeedsConfirmation" class="confirmation-check"><input v-model="paidTtsConfirmed"
                            type="checkbox" :disabled="!providerReady || !canGenerate" /><span>我确认本次将提交一次语音合成，并承担正式
                            Provider 调用费用。</span></label>
                    <span v-else-if="providerIsDemo" class="provider-demo-note">演示模式：无需费用确认，仅生成可试听的演示音频。</span>
                    <div class="tts-actions">
                        <SfxButton v-if="selectedTtsJob?.status === 'failed'" size="sm" :disabled="!canSubmitTts"
                            :loading="acting === 'retry-tts'" @click="retryTts">确认并重试一次</SfxButton>
                        <SfxButton v-else size="sm" :disabled="!canSubmitTts" :loading="acting === 'submit-tts'"
                            @click="submitTts">
                            <Send :size="14" /> 为当前讲稿提交语音（单知识点）
                        </SfxButton>
                        <small v-if="!providerReady">先等待服务器端语音服务健康检查通过。</small>
                    </div>
                </div>

                <article class="workflow-row"
                    :class="{ complete: releaseCueAssetsReady, active: selectedTtsJob?.status === 'succeeded' && !releaseCueAssetsReady }">
                    <div class="workflow-icon">
                        <Captions :size="18" />
                    </div>
                    <div class="workflow-copy"><span>02 · 字幕与时间轴</span><strong>冻结字幕、说话区间和 PPT 映射快照</strong>
                        <p v-if="isPlaylistRelease && batchReady">本批全部知识点均已生成字幕清单（subtitle-manifest/v1）。</p>
                        <p v-else-if="hasFrozenCues">已生成字幕清单（subtitle-manifest/v1）。</p>
                        <p v-else-if="cueJob">
                            {{ jobStatusLabel(cueJob) }} ·
                            {{ cueJob.error_message_safe || TTS_FALLBACK }}
                        </p>
                        <p v-else>需要成功 TTS；缺少音素时仅生成字级/字幕驱动的通用说话状态，不宣称精确口型。</p>
                    </div>
                    <SfxBadge :tone="releaseCueAssetsReady ? 'green' : cueJob ? jobTone(cueJob) : 'neutral'">{{
                        releaseCueAssetsReady ? '已冻结' : cueJob ? jobStatusLabel(cueJob) : '等待 TTS' }}</SfxBadge>
                </article>
                <div v-if="!isPlaylistRelease && selectedTtsJob?.status === 'succeeded' && !hasFrozenCues && (!cueJob || cueJob.status === 'failed')"
                    class="workflow-action">
                    <SfxButton size="sm" :disabled="!canGenerate" :loading="acting === 'freeze-cues'"
                        @click="freezeCues">冻结字幕与时间轴</SfxButton>
                </div>

                <article class="workflow-row"
                    :class="{ complete: hasPptManifest, active: canBuildPptManifest && !hasPptManifest }">
                    <div class="workflow-icon">
                        <FileImage :size="18" />
                    </div>
                    <div class="workflow-copy"><span>03 · PPT manifest</span><strong>冻结学生端播放所需的 PPT 页图清单</strong>
                        <p v-if="hasPptManifest">PPT manifest 已绑定到此媒体草稿。</p><template v-else-if="pptManifestInFlight">
                            <p>正在复用映射阶段缓存的 PPT 页图；只有缺失页面才会在后台补渲染。</p>
                            <p v-if="pptManifestProgress" class="task-output">页图进度：{{
                                pptManifestProgress.completed_pages || 0 }}/{{ pptManifestProgress.total_pages || '待确认'
                                }}；缓存 {{ pptManifestProgress.cached_pages || 0 }} 页，待补 {{
                                    pptManifestProgress.missing_pages || 0 }} 页。</p>
                        </template>
                        <p v-else-if="pptManifestJob?.status === 'failed'">{{ pptManifestJob.error_message_safe ||
                            PPT_FAILED_FALLBACK }}</p>
                        <p v-else-if="isPlaylistRelease">批量模式：需全部知识点音频与 Cue 就绪后生成；缺少 PPT 源文件时服务端会返回明确阻塞原因。</p>
                        <p v-else>如果第 04 步尚无可渲染 PPT/PDF 源文件，本步骤会明确返回阻塞原因；可先回到映射页处理。</p>
                    </div>
                    <SfxBadge :tone="hasPptManifest ? 'green' : pptManifestJob ? jobTone(pptManifestJob) : 'amber'">{{
                        hasPptManifest ?
                            '已冻结' : pptManifestJob ? jobStatusLabel(pptManifestJob) : '可选但建议完成' }}</SfxBadge>
                </article>
                <div v-if="canBuildPptManifest && !hasPptManifest" class="workflow-action">
                    <SfxButton v-if="!pptManifestInFlight" variant="secondary" size="sm"
                        :disabled="!canGenerate || acting === 'ppt-manifest'" @click="createPptManifest">{{
                            pptManifestJob?.status ===
                                'failed' ? '重试 PPT manifest' : '生成 PPT manifest' }}</SfxButton><small v-else>后台任务执行中；本页面每 5
                        秒刷新一次进度，无需保持本次请求。</small>
                </div>
                <div v-if="isPlaylistRelease" class="workflow-action">
                    <p v-if="hasFrozenPlaylist" class="task-output">课程播放清单已固定到此版本，后续不会自动更改。</p>
                    <SfxButton v-else variant="secondary" size="sm" :disabled="!canGenerate || !hasPptManifest"
                        :loading="acting === 'batch-freeze'" @click="freezeBatchPlaylist">冻结课程播放清单</SfxButton>
                    <small v-if="!hasPptManifest">需先完成 PPT 页面映射；有知识点未生成或映射缺失时，无法最终发布。</small>
                </div>

                <article class="workflow-row"
                    :class="{ complete: workingRelease.status === 'active', active: canActivateWorkingRelease && workingRelease.status === 'draft' }">
                    <div class="workflow-icon">
                        <Check :size="18" />
                    </div>
                    <div class="workflow-copy"><span>04 · 激活并固化到课程发布</span><strong>激活媒体版本，再重新正式发布课程</strong>
                        <p v-if="workingRelease.status === 'active'">媒体已激活；课程正式发布时会把它写入不可变媒体快照。</p>
                        <p v-else>激活不会自动改写学生当前课程版本。完成激活后仍需到第 07 步重新正式发布。</p>
                    </div>
                    <SfxBadge :tone="workingRelease.status === 'active' ? 'green' : 'amber'">{{ workingRelease.status
                        === 'active' ?
                        '已激活' : '等待激活' }}</SfxBadge>
                </article>
                <div v-if="workingRelease.status === 'draft'" class="workflow-action">
                    <SfxButton size="sm" :disabled="!canPublish || !canActivateWorkingRelease"
                        :loading="acting === 'activate'" @click="activateRelease">激活媒体版本</SfxButton>
                </div>
                <div v-else-if="workingRelease.status === 'active'" class="workflow-action">
                    <SfxButton variant="secondary" size="sm" @click="goToRelease">前往正式发布</SfxButton>
                </div>
            </div>
        </template>
    </section>
</template>

<style scoped>
.release-panel {
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    background: var(--surface-panel);
    overflow: hidden;
    flex-shrink: 0;
}

.panel-heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border-subtle);
}

.panel-heading p {
    margin: 0;
    color: var(--text-muted);
    font-size: var(--caption-size);
    font-weight: 600;
    letter-spacing: .04em;
}

.panel-heading h3 {
    margin: 2px 0 0;
    color: var(--text-primary);
    font-size: var(--ui-md-size);
}

.release-picker {
    display: flex;
    gap: var(--space-1);
    /* 横向滚动容器：版本按钮超出时横向滚动而非挤压 */
    overflow-x: auto;
    scrollbar-width: thin;
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--border-subtle);
}

/* 子盒子：不收缩并给定最小宽度，保证横向滚动条真正出现 */
.release-picker .sfx-btn {
    flex: 0 0 auto;
    min-width: 100px;
}

.release-empty {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-6);
    color: var(--text-muted);
}

.release-empty>div {
    display: grid;
    gap: var(--space-1);
    min-width: 0;
    flex: 1;
}

.release-empty strong {
    color: var(--text-primary);
    font-size: var(--ui-md-size);
}

.release-empty p {
    margin: 0;
    font-size: var(--ui-sm-size);
    line-height: 1.5;
}

.binding-warning {
    display: grid;
    grid-template-columns: 20px minmax(0, 1fr) auto;
    align-items: start;
    gap: var(--space-2);
    padding: var(--space-4);
    background: var(--amber-100);
    color: var(--amber-700);
}

.binding-warning div {
    display: grid;
    gap: var(--space-1);
}

.binding-warning strong {
    color: var(--text-primary);
    font-size: var(--ui-md-size);
}

.binding-warning p {
    margin: 0;
    font-size: var(--ui-sm-size);
    line-height: 1.5;
}

.workflow-list {
    display: grid;
}

.workflow-row {
    display: grid;
    grid-template-columns: 34px minmax(0, 1fr) auto;
    gap: var(--space-3);
    align-items: start;
    padding: var(--space-4);
    border-bottom: 1px solid var(--border-subtle);
}

.workflow-row.active {
    background: var(--ink-100);
}

.workflow-icon {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    border-radius: var(--radius-full);
    background: var(--surface-cool);
    color: var(--ink-700);
}

.workflow-row.complete .workflow-icon {
    color: var(--green-700);
}

.workflow-copy {
    display: grid;
    gap: 2px;
    min-width: 0;
}

.workflow-copy>span {
    color: var(--text-muted);
    font-size: var(--caption-size);
    font-weight: 600;
    letter-spacing: .04em;
}

.workflow-copy strong {
    color: var(--text-primary);
    font-size: var(--ui-md-size);
    line-height: 1.45;
}

.workflow-copy p {
    margin: 0;
    color: var(--text-secondary);
    font-size: var(--ui-sm-size);
    line-height: 1.5;
}

.tts-confirmation {
    margin: 0 0 var(--space-3);
    padding: var(--space-3);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm);
    background: var(--surface-cool);
}

.confirmation-check {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    color: var(--text-secondary);
    font-size: var(--ui-sm-size);
    line-height: 1.5;
}

.confirmation-check input {
    width: 16px;
    height: 16px;
    margin: 2px 0 0;
    accent-color: var(--ink-700);
    flex-shrink: 0;
}

.tts-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
    margin-top: var(--space-3);
}

.tts-actions small {
    color: var(--text-muted);
    font-size: var(--caption-size);
}

.workflow-action {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: var(--space-3);
    flex-wrap: wrap;
    margin: 0 0 var(--space-3);
}

.task-error {
    color: var(--red-700);
}

.task-output {
    color: var(--green-700);
}

.provider-demo-note {
    color: var(--ink-700);
    font-size: var(--caption-size);
}

@media (max-width: 700px) {
    .workflow-row {
        grid-template-columns: 34px minmax(0, 1fr);
    }

    .workflow-row>.sfx-badge {
        grid-column: 2;
    }

    .binding-warning {
        grid-template-columns: 20px minmax(0, 1fr);
    }

    .binding-warning .sfx-btn {
        grid-column: 2;
        justify-self: start;
    }

    .release-empty {
        align-items: flex-start;
        flex-wrap: wrap;
    }

    .release-empty .sfx-btn {
        margin-left: 35px;
    }

    .tts-actions {
        align-items: flex-start;
        flex-direction: column;
    }
}
</style>
