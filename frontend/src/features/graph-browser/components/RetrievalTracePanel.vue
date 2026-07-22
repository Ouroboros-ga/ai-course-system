<template>
  <section class="gb-trace">
    <div class="panel-heading">
      <div>
        <p>检索轨迹</p>
        <small>RetrievalTrace / trace_schema_version（报告 §检索与证据协议）</small>
      </div>
      <span class="badge shadow">影子未放量</span>
    </div>

    <div v-if="!trace" class="trace-empty">
      <Hourglass :size="18" />
      <div>
        <p class="t1">尚无真实检索轨迹可显示</p>
        <p class="t2">
          检索阶段时间线（解析 → 召回 → 重排 → 生成）依赖后端
          <code>RetrievalTrace</code> 与 <code>trace_schema_version=1</code> 契约，目前为 V2 影子、
          未接真模型也未放量。此处不伪造任何阶段或耗时。
        </p>
      </div>
    </div>

    <ol v-else class="trace-list">
      <li v-for="stage in trace.stages" :key="stage.name" class="stage">
        <span class="dot" />
        <div class="stage-body">
          <div class="stage-head">
            <strong>{{ stage.name }}</strong>
            <span class="ms">{{ stage.durationMs ?? '—' }} ms</span>
          </div>
          <p v-if="stage.detail" class="stage-detail">{{ stage.detail }}</p>
        </div>
      </li>
    </ol>
  </section>
</template>

<script setup>
/**
 * RetrievalTracePanel — renders a real RetrievalTrace when one exists.
 *
 * Per report discipline ("只可视化真实存在的能力"), when no trace payload is
 * available (V2 shadow not enabled / not wired to a real provider), the panel
 * shows an explicit empty state instead of fabricating stages.
 */
import { Hourglass } from 'lucide-vue-next'

defineProps({
  // null => no real trace available (show empty state, do not fabricate)
  trace: { type: Object, default: null },
})
</script>

<style scoped>
.gb-trace { background: var(--color-bg-primary, #fff); border: 1px solid var(--color-border, #d9e1ea); border-radius: 12px; padding: 14px; }
.panel-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.panel-heading p { margin: 0; font-size: 14px; font-weight: 700; color: var(--color-text-primary, #1e293b); }
.panel-heading small { display: block; color: var(--color-text-tertiary, #94a3b8); font-size: 11px; margin-top: 2px; }
.badge { font-size: 11px; padding: 3px 8px; border-radius: 999px; white-space: nowrap; }
.badge.shadow { background: #fffbeb; color: #a16207; border: 1px solid #fde68a; }
.trace-empty { margin-top: 12px; display: flex; gap: 10px; padding: 12px; background: var(--color-bg-secondary, #f8fafc); border: 1px dashed var(--color-border, #cbd5e1); border-radius: 8px; color: var(--color-text-secondary, #475569); }
.trace-empty .t1 { margin: 0; font-size: 13px; font-weight: 600; color: var(--color-text-primary, #1e293b); }
.trace-empty .t2 { margin: 4px 0 0; font-size: 12px; line-height: 1.6; }
.trace-empty code { background: var(--color-bg-primary, #fff); padding: 1px 4px; border-radius: 4px; font-size: 11px; }
.trace-list { margin: 12px 0 0; padding: 0; list-style: none; }
.stage { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--color-border, #eef2f7); }
.stage:last-child { border-bottom: 0; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--color-primary, #1769aa); margin-top: 5px; flex: none; }
.stage-head { display: flex; justify-content: space-between; gap: 10px; font-size: 13px; color: var(--color-text-primary, #1e293b); }
.ms { color: var(--color-text-tertiary, #94a3b8); font-variant-numeric: tabular-nums; }
.stage-detail { margin: 3px 0 0; font-size: 12px; color: var(--color-text-secondary, #475569); }
</style>
