<script setup>
import { provide } from 'vue'
import { Sparkles } from 'lucide-vue-next'
import SfxError from '@/app/ui/SfxError.vue'
import SfxSkeleton from '@/app/ui/SfxSkeleton.vue'
import { useMediaBuild } from './media/useMediaBuild.js'
import ScriptRail from './media/ScriptRail.vue'
import ProviderStatusBar from './media/ProviderStatusBar.vue'
import BatchMediaPanel from './media/BatchMediaPanel.vue'
import SelectedScriptPanel from './media/SelectedScriptPanel.vue'
import PreviewPanel from './media/PreviewPanel.vue'
import ReleaseWorkflowPanel from './media/ReleaseWorkflowPanel.vue'
import TaskListPanel from './media/TaskListPanel.vue'
import PreviewDock from './media/PreviewDock.vue'

// 逻辑统一收敛到 useMediaBuild；各面板组件通过 provide/inject 共享同一份状态。
const mediaBuild = useMediaBuild()
provide('mediaBuild', mediaBuild)

const { state, error, load, selectedScript } = mediaBuild
</script>

<template>
    <section class="media-stage">
        <SfxSkeleton v-if="state === 'loading'" :lines="7" block />
        <SfxError v-else-if="state === 'error'" :description="error" @retry="load" />

        <div v-else class="media-workbench">
            <ScriptRail />

            <main class="media-main">
                <ProviderStatusBar />
                <BatchMediaPanel />

                <template v-if="selectedScript">
                    <SelectedScriptPanel />
                    <PreviewPanel />
                    <ReleaseWorkflowPanel />
                    <TaskListPanel />
                </template>
                <div v-else class="main-empty">
                    <Sparkles :size="28" /><strong>先生成讲稿，再创建课堂媒体</strong>
                    <p>媒体中心只处理已确认的讲稿节点，因此不会凭空生成或猜测教学内容。</p>
                </div>

                <PreviewDock />
            </main>
        </div>
    </section>
</template>

<style scoped>
.media-stage {
    height: 100%;
    min-height: 0;
    display: grid;
    grid-template-rows: minmax(0, 1fr);
    overflow: hidden;
}

.media-workbench {
    display: grid;
    grid-template-columns: 272px minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr);
    min-height: 0;
    border: 1px solid var(--border-default);
    border-radius: var(--radius-lg);
    overflow: hidden;
    background: var(--surface-canvas);
}

.media-main {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    min-width: 0;
    min-height: 0;
    overflow-y: auto;
    padding: var(--space-3) var(--space-6);
}

.main-empty {
    display: grid;
    place-items: center;
    align-content: center;
    gap: var(--space-2);
    min-height: 300px;
    color: var(--text-muted);
    text-align: center;
}

.main-empty strong {
    color: var(--text-primary);
    font-size: var(--title-3-size);
}

.main-empty p {
    max-width: 380px;
    margin: 0;
    font-size: var(--ui-sm-size);
    line-height: 1.5;
}

@media (max-width: 960px) {
    .media-workbench {
        grid-template-columns: 220px minmax(0, 1fr);
    }
}

@media (max-width: 700px) {
    .media-stage {
        height: auto;
        overflow: visible;
    }

    .media-workbench {
        grid-template-columns: 1fr;
        grid-template-rows: auto auto;
        overflow: visible;
    }

    .media-main {
        overflow: visible;
        padding: var(--space-3);
    }
}
</style>
