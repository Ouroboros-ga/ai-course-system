<script setup>
import { inject } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import SfxBadge from '@/app/ui/SfxBadge.vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const mediaBuild = inject('mediaBuild')
const { jobs, jobLabel, jobTone, jobStatusLabel, formatDate, scripts, scriptLabel, refreshing, load } = mediaBuild
</script>

<template>
    <section class="task-panel" aria-labelledby="task-title">
        <header class="panel-heading">
            <div>
                <p>已提交的合成与冻结任务</p>
                <h3 id="task-title">媒体任务记录</h3>
            </div>
            <SfxButton variant="tertiary" size="sm" :loading="refreshing" @click="load">
                <RefreshCw :size="14" /> 刷新
            </SfxButton>
        </header>
        <div v-if="jobs.length" class="task-list">
            <article v-for="job in jobs.slice(0, 12)" :key="job.job_id" class="task-row">
                <div><strong>{{ jobLabel(job) }}</strong><span>{{scripts.find((item) => item.script_node_db_id ===
                    job.node_id) ? scriptLabel(scripts.find((item) => item.script_node_db_id === job.node_id)) :
                        '未关联讲稿节点' }}</span></div>
                <SfxBadge :tone="jobTone(job)">{{ jobStatusLabel(job) }}</SfxBadge>
                <span class="task-time">{{ formatDate(job.finished_at || job.created_at) }}</span>
                <p v-if="job.error_message_safe" class="task-error">{{ job.error_message_safe }}</p>
                <p v-else-if="job.output_object_key" class="task-output">已生成受课程权限保护的媒体对象</p>
            </article>
        </div>
        <p v-else class="task-empty">还没有媒体任务。创建草稿并明确提交 TTS 后，状态会在这里保留。</p>
    </section>
</template>

<style scoped>
.task-panel {
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

.task-list {
    display: grid;
    max-height: 280px;
    overflow-y: auto;
}

.task-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    gap: var(--space-3);
    align-items: center;
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border-subtle);
}

.task-row:last-child {
    border-bottom: 0;
}

.task-row>div {
    display: grid;
    gap: 2px;
    min-width: 0;
}

.task-row strong,
.task-row span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.task-row strong {
    color: var(--text-primary);
    font-size: var(--ui-sm-size);
}

.task-row span {
    color: var(--text-muted);
    font-size: var(--caption-size);
}

.task-time {
    justify-self: end;
    white-space: nowrap;
}

.task-row .task-error,
.task-row .task-output {
    grid-column: 1 / -1;
    margin: 0;
    font-size: var(--caption-size);
    line-height: 1.45;
}

.task-error {
    color: var(--red-700);
}

.task-output {
    color: var(--green-700);
}

.task-empty {
    margin: 0;
    padding: var(--space-6);
    color: var(--text-muted);
    font-size: var(--ui-sm-size);
    text-align: center;
}

@media (max-width: 960px) {
    .task-row {
        grid-template-columns: minmax(0, 1fr) auto;
    }

    .task-time {
        display: none;
    }
}

@media (max-width: 700px) {
    .task-list {
        max-height: none;
        overflow: visible;
    }

    .task-row {
        grid-template-columns: minmax(0, 1fr) auto;
    }
}
</style>
