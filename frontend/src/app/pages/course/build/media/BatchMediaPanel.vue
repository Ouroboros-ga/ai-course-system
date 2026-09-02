<script setup>
import { inject } from 'vue'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const mediaBuild = inject('mediaBuild')
const {
    presetCatalog,
    selectedVoicePresetId, selectedVoicePresetVersion,
    batchPlan, batchPlanMatchesSelections, canPlanBatch, createBatchPlan,
    providerNeedsConfirmation, providerIsDemo, paidTtsConfirmed,
    canConfirmBatch, confirmBatch, acting,
    batchState, batchAlreadySubmitted, batchStatusLabel, batchItems, batchItemStatusLabel,
    findScriptForBatchItem, scriptLabel, batchNodeIds,
} = mediaBuild
</script>

<template>
    <section class="release-panel batch-panel" aria-labelledby="batch-title">
        <header class="panel-heading">
            <div>
                <p>P4 批量媒体建设</p>
                <h3 id="batch-title">在左侧勾选知识点，一次确认后批量生成</h3>
            </div>
            <SfxBadge tone="ink">{{ batchNodeIds.length }} / 20</SfxBadge>
        </header>
        <div v-if="presetCatalog.voices.length" class="preset-selection">
            <div class="preset-group">
                <span class="preset-label">平台音色</span>
                <label v-for="voice in presetCatalog.voices" :key="`voice-${voice.preset_id}-${voice.version}`"
                    class="preset-option"
                    :class="{ selected: selectedVoicePresetId === voice.preset_id && selectedVoicePresetVersion === voice.version }">
                    <input v-model="selectedVoicePresetId" type="radio" name="media-voice-preset"
                        :value="voice.preset_id" @change="selectedVoicePresetVersion = voice.version" />
                    <span><strong>{{ voice.display_name }}</strong><small>{{ voice.version }} · {{ voice.provider_key
                    }}</small></span>
                </label>
            </div>
        </div>
        <div v-if="batchPlan" class="batch-estimate">
            <span>节点 {{ batchPlan.node_count }}</span><span>总字符 {{ batchPlan.total_chars }}</span><span>待计费 {{
                batchPlan.billable_chars }}</span><span>缓存命中 {{ batchPlan.cache_hit_count }}</span>
            <p v-if="batchPlan.blocking_reasons?.length" class="task-error">{{ [...new
                Set(batchPlan.blocking_reasons)].join('；') }}；试听可随时进行，但最终发布前需完成全部映射。</p>
            <p v-if="!batchPlanMatchesSelections" class="task-error">音色已变更，请重新核算后再确认；不能用旧估算冻结新版本。</p>
            <p class="estimate-cap">单批核算上限 {{ batchPlan.max_chars }} 个计费字符 · 单个讲稿超 {{
                batchPlan.max_script_bytes }} 字节无法生成</p>
        </div>
        <div class="tts-actions">
            <span v-if="providerIsDemo" class="provider-demo-note">演示模式：使用本地合成，不产生费用。</span>
            <SfxButton variant="secondary" size="sm" :disabled="!canPlanBatch" :loading="acting === 'batch-plan'"
                @click="createBatchPlan">核算批量费用</SfxButton>
            <label v-if="providerNeedsConfirmation" class="confirmation-check"><input v-model="paidTtsConfirmed"
                    type="checkbox" :disabled="!batchPlan" /> 我确认本批可能产生 TTS Provider 费用</label>
            <SfxButton size="sm" :disabled="!canConfirmBatch" :loading="acting === 'batch-confirm'"
                @click="confirmBatch" :title="batchAlreadySubmitted
                    ? '本批任务已提交；同一批节点与音色组合不会重复生成（幂等）。如需重新生成请调整勾选节点或音色后重新核算。'
                    : '一次提交所选全部知识点的语音合成，并自动冻结字幕与时间轴；无需在下方重复手动提交'">{{
                    batchAlreadySubmitted ? '已提交，处理中（本批不会重复生成）' : '生成全部所选知识点语音'
                }}</SfxButton>
        </div>
        <p class="batch-flow-hint">此步包含全部所选知识点的语音合成（字幕与时间轴自动冻结）；完成后按下方步骤依次执行 PPT manifest → 冻结播放清单 → 激活 → 正式发布。</p>
        <div v-if="batchState" class="batch-status" role="status">
            <span>批次状态：{{ batchStatusLabel(batchState.status) }}</span>
            <span>已完成 {{batchItems.filter(item => item.status === 'ready').length}} / {{ batchItems.length }}</span>
        </div>
        <div v-if="batchItems.length" class="batch-item-list" aria-label="批量媒体节点状态">
            <article v-for="item in batchItems" :key="item.item_id || item.node_id" class="batch-item-row">
                <div><strong>{{ findScriptForBatchItem(item) ? scriptLabel(findScriptForBatchItem(item)) : '知识点 ' +
                        item.node_id }}</strong><small>{{ batchItemStatusLabel(item.status) }}{{
                            item.error_message_safe ? ` · ${item.error_message_safe}` : '' }}</small></div>
                <SfxBadge
                    :tone="item.status === 'ready' ? 'green' : item.status === 'failed' || item.status === 'blocked' ? 'red' : 'amber'">
                    {{ batchItemStatusLabel(item.status) }}</SfxBadge>
            </article>
        </div>
    </section>
</template>

<style scoped>
.batch-panel {
    border: 1px solid var(--border-strong);
    background: var(--surface-panel);
}

.batch-panel .tts-actions {
    flex-wrap: wrap;
    margin-top: 0;
    padding: var(--space-3) var(--space-4);
    border-top: 1px solid var(--border-subtle);
    background: var(--surface-cool);
}

.batch-panel .tts-actions .sfx-btn {
    flex: 1 1 auto;
    min-width: max-content;
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

.batch-estimate {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-4);
    padding: var(--space-3) var(--space-4);
    color: var(--text-secondary);
    font-size: var(--ui-sm-size);
}

.batch-estimate p {
    flex-basis: 100%;
    margin: 0;
}

.batch-flow-hint {
    margin: 0;
    padding: var(--space-2) var(--space-4) var(--space-3);
    color: var(--text-muted);
    font-size: var(--caption-size);
    line-height: 1.5;
    border-top: 1px solid var(--border-subtle);
}

.batch-status {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-4);
    border-top: 1px solid var(--border-subtle);
    color: var(--text-secondary);
    font-size: var(--caption-size);
}

.batch-item-list {
    display: grid;
    border-top: 1px solid var(--border-subtle);
}

.batch-item-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-4);
    border-bottom: 1px solid var(--border-subtle);
}

.batch-item-row>div {
    display: grid;
    gap: 2px;
    min-width: 0;
}

.batch-item-row strong {
    color: var(--text-primary);
    font-size: var(--ui-sm-size);
}

.batch-item-row small {
    color: var(--text-secondary);
    font-size: var(--caption-size);
    overflow-wrap: anywhere;
}

.preset-selection {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border-subtle);
}

.preset-group {
    display: grid;
    gap: var(--space-2);
    min-width: 0;
}

.preset-label {
    color: var(--text-muted);
    font-size: var(--caption-size);
    font-weight: 600;
    letter-spacing: .04em;
}

.preset-option {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    padding: var(--space-2);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-sm);
    background: var(--surface-panel);
    cursor: pointer;
}

.preset-option.selected {
    border-color: var(--ink-500);
    background: var(--ink-100);
}

.preset-option input {
    width: 16px;
    height: 16px;
    margin: 2px 0 0;
    accent-color: var(--ink-700);
    flex-shrink: 0;
}

.preset-option span {
    display: grid;
    gap: 2px;
    min-width: 0;
}

.preset-option strong {
    color: var(--text-primary);
    font-size: var(--ui-sm-size);
}

.preset-option small {
    color: var(--text-secondary);
    font-size: var(--caption-size);
    overflow-wrap: anywhere;
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

.task-error {
    color: var(--red-700);
}

.estimate-cap {
    color: var(--text-muted);
    font-size: var(--caption-size);
}

.provider-demo-note {
    color: var(--ink-700);
    font-size: var(--caption-size);
}

@media (max-width: 700px) {
    .preset-selection {
        grid-template-columns: 1fr;
    }

    .tts-actions {
        align-items: flex-start;
        flex-direction: column;
    }
}
</style>
