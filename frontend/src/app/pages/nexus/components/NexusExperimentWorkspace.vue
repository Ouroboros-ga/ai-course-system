<script setup>
/**
 * NexusLab 实验工作台（主舞台视图）
 *
 * 位置：Research 会话的第二个视图（与研究对话同会话、同一份 run 数据），
 * 不是独立页面、不新增路由。顶部视图切换器固定在右上角，由父组件渲染。
 *
 * 设计依据：docs/phase1/2026-09-07_NexusLab_研究与实验一体化设计板_v6.html
 *
 * 硬规则：
 * - fail-closed：缺数据一律显示「未建立 / 不适用」，不回退演示数字；
 * - 运行中的退出码显示「—」，终态如实显示（含 -9）；
 * - 取消走独立 cancel API，禁止用聊天 Stop 冒充；
 * - 结果判定只来自服务端 report（verdict/comparison），前端绝不自行计算。
 */
import { computed, ref } from 'vue'
import {
  FlaskConical,
  FileText,
  LineChart,
  MessageSquare,
  RotateCw,
  Square,
  TriangleAlert
} from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'
import {
  reproCancellable,
  reproElapsed,
  reproIsCurrentStep,
  reproLogSource,
  reproStageNotes,
  reproStageRail,
  reproStatusLabel,
  reproStepLabel,
  reproStepState
} from '../reproShared.js'

const props = defineProps({
  /** 本会话所有 run：[{ id, name, run }]，id 为 turn 标识，name 由父按 v6 规则生成 */
  runs: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
  /** 当前 run 关联产物（turn.artifacts） */
  artifacts: { type: Array, default: () => [] },
  cancelling: { type: Boolean, default: false }
})

const emit = defineEmits(['switch', 'cancel', 'ask', 'analyze', 'rerun'])

const tab = ref('logs')

const active = computed(() => props.runs.find((r) => r.id === props.activeId) || props.runs[0] || null)
const run = computed(() => active.value?.run || null)
const rail = computed(() => (run.value ? reproStageRail(run.value) : []))
const notes = computed(() => (run.value ? reproStageNotes(run.value) : ''))
const elapsed = computed(() => (run.value ? reproElapsed(run.value) : ''))
const cancellable = computed(() => reproCancellable(run.value))

const TABS = [
  { key: 'logs', label: '日志' },
  { key: 'metrics', label: '指标' },
  { key: 'artifacts', label: '产物' }
]

const statusClass = computed(() => {
  const s = run.value?.status
  if (s === 'succeeded') return 'is-ok'
  if (['failed', 'rejected'].includes(s)) return 'is-err'
  if (['running', 'queued', 'cancelling'].includes(s)) return 'is-run'
  return 'is-idle'
})

const logText = computed(() => {
  if (!run.value) return ''
  if (['running', 'cancelling', 'queued'].includes(run.value.status) && run.value.liveLog) {
    return run.value.liveLog
  }
  const withLog = (run.value.stages || []).filter((s) => s.log_tail)
  return withLog.length ? withLog[withLog.length - 1].log_tail : ''
})

/** 配置区只展示 run 记录里真实存在的字段，缺字段显示「未建立」而不是猜值 */
const configRows = computed(() => {
  const r = run.value
  if (!r) return []
  return [
    { k: 'preset', v: r.preset_id || '未建立' },
    { k: 'job_id', v: r.job_id || '未建立' },
    { k: 'seed', v: r.seedUsed ? '已固定' : '未固定' },
    { k: '步骤', v: `${(r.stages || []).length || '—'}` },
    { k: '当前步', v: ['running', 'cancelling'].includes(r.status) ? String(r.currentStep ?? '—') : '—' }
  ]
})

const steps = computed(() => (run.value?.stages || []).map((s) => ({
  index: s.index,
  command: s.command || '',
  exit_code: s.exit_code,
  duration_s: s.duration_s,
  timed_out: s.timed_out,
  log_tail: s.log_tail || ''
})))

function stepState(step) {
  return reproStepState(run.value, step)
}
function stepLabel(step) {
  return reproStepLabel(run.value, step)
}
function isCurrent(step) {
  return reproIsCurrentStep(run.value, step.index)
}
function exitLabel(step) {
  return step.exit_code == null ? '—' : String(step.exit_code)
}
function durationLabel(step) {
  if (step.duration_s == null) return '—'
  return step.duration_s >= 60
    ? `${Math.floor(step.duration_s / 60)}m${String(Math.round(step.duration_s % 60)).padStart(2, '0')}s`
    : `${Number(step.duration_s).toFixed(2)}s`
}

const hasReport = computed(() => !!run.value?.verdict)
const reportErr = computed(() => run.value?.reportError || '')
</script>

<template>
  <section v-if="active" class="nxw">
    <!-- 头部：状态 + run 切换 + 动作。
         实验名与视图切换器固定在页面顶栏（v6 定版：左上名、右上切换），
         这里不重复一遍——重复正是上一版被判「臃肿」的原因之一。 -->
    <header class="nxw-head">
      <span class="nxw-st" :class="statusClass">
        <i class="nxw-dot" />
        {{ reproStatusLabel(run) }}
      </span>
      <span v-if="elapsed" class="nxw-elapsed">{{ elapsed }}</span>

      <span class="nxw-spacer" />

      <label v-if="runs.length > 1" class="nxw-runsel">
        <span class="nxw-runsel-label">本次运行</span>
        <select :value="active.id" class="nxw-select" @change="emit('switch', $event.target.value)">
          <option v-for="r in runs" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
      </label>

      <SfxButton variant="tertiary" size="sm" @click="emit('ask', active.id)">
        <template #icon><MessageSquare :size="13" /></template>
        询问 Nexus
      </SfxButton>

      <SfxButton
        v-if="cancellable"
        variant="secondary"
        size="sm"
        :loading="cancelling"
        @click="emit('cancel', active.id)"
      >
        <template #icon><Square :size="12" /></template>
        取消
      </SfxButton>
      <template v-else-if="hasReport">
        <SfxButton variant="primary" size="sm" @click="emit('analyze', active.id)">
          <template #icon><FlaskConical :size="13" /></template>
          分析本次结果
        </SfxButton>
        <SfxButton variant="secondary" size="sm" @click="emit('rerun', active.id)">
          <template #icon><RotateCw :size="13" /></template>
          调整方案再运行
        </SfxButton>
      </template>
    </header>

    <!-- 阶段条：六段固定轨道，状态来自 Worker 真实 stage_events -->
    <div class="nxw-stagebar" role="list" aria-label="执行阶段">
      <template v-for="(st, i) in rail" :key="st.stage">
        <div v-if="i" class="nxw-stgline" :class="{ 'is-done': st.state === 'done' }" />
        <div class="nxw-stg" :class="`is-${st.state}`" role="listitem" :title="st.note || st.label">
          <i class="nxw-stgdot" />
          <span>{{ st.label }}</span>
          <span v-if="st.state === 'skipped'" class="nxw-stgnote">不适用</span>
        </div>
      </template>
    </div>
    <p v-if="notes" class="nxw-stagenotes">{{ notes }}</p>

    <!-- 主体：左配置/步骤 · 右输出 -->
    <div class="nxw-body">
      <aside class="nxw-side">
        <div class="nxw-cap">运行配置 · 只读</div>
        <div v-for="row in configRows" :key="row.k" class="nxw-kv">
          <span>{{ row.k }}</span>
          <b>{{ row.v }}</b>
        </div>

        <div class="nxw-cap">步骤 · {{ steps.length }}</div>
        <ol class="nxw-steps">
          <li
            v-for="s in steps"
            :key="s.index"
            class="nxw-step"
            :class="`is-${stepState(s)}`"
          >
            <div class="nxw-cmd">{{ s.command || '（命令未返回）' }}</div>
            <div class="nxw-meta">
              <span class="nxw-ex">exit {{ exitLabel(s) }}</span>
              <span>{{ durationLabel(s) }}</span>
              <span v-if="isCurrent(s)" class="nxw-runbadge">进行中</span>
              <span v-else class="nxw-statetext">{{ stepLabel(s) }}</span>
            </div>
            <div v-if="isCurrent(s) && s.log_tail" class="nxw-tail">{{ s.log_tail }}</div>
          </li>
        </ol>
        <p v-if="!steps.length" class="nxw-empty">尚无步骤记录（作业未开始或 Worker 未返回）。</p>
      </aside>

      <section class="nxw-out">
        <div class="nxw-tabs">
          <span
            v-for="t in TABS"
            :key="t.key"
            class="nxw-tab"
            :class="{ 'is-on': tab === t.key }"
            role="tab"
            :aria-selected="tab === t.key"
            @click="tab = t.key"
          >
            {{ t.label }}
            <b v-if="t.key === 'artifacts' && artifacts.length" class="nxw-tabn">{{ artifacts.length }}</b>
          </span>
          <span class="nxw-spacer" />
          <span v-if="tab === 'logs' && logText" class="nxw-logsrc">{{ reproLogSource(run) }}</span>
        </div>

        <!-- 日志：唯一深色语境 -->
        <div v-if="tab === 'logs'" class="nxw-term" :class="{ 'is-empty': !logText }">
          <pre v-if="logText" class="nxw-log">{{ logText }}</pre>
          <p v-else class="nxw-empty">暂无日志输出。</p>
        </div>

        <!-- 指标：只渲染服务端 report，绝不自行计算 -->
        <div v-else-if="tab === 'metrics'" class="nxw-pane">
          <div v-if="hasReport" class="nxw-verdict" :class="run.verdict === 'PASS' ? 'is-pass' : 'is-fail'">
            <span class="nxw-verdict-label">指标判定</span>
            <b>{{ run.verdict }}</b>
            <span class="nxw-verdict-src">源：GET /nexus/repro/jobs/{id}/report</span>
          </div>
          <table v-if="run.comparison && run.comparison.length" class="nxw-table">
            <thead>
              <tr><th>指标</th><th>实测</th><th>期望</th></tr>
            </thead>
            <tbody>
              <tr v-for="(c, i) in run.comparison" :key="i">
                <td>{{ c.metric || c.name || '—' }}</td>
                <td class="is-num">{{ c.actual ?? c.value ?? '—' }}</td>
                <td class="is-num">{{ c.expected ?? c.target ?? '未声明' }}</td>
              </tr>
            </tbody>
          </table>
          <div class="nxw-na">
            <LineChart :size="14" />
            <span>loss 曲线：后端只提供终值，不提供时序 —— 不画假曲线。</span>
          </div>
          <p v-if="!hasReport && reportErr" class="nxw-err">
            <TriangleAlert :size="13" /> {{ reportErr }}
          </p>
          <p v-else-if="!hasReport" class="nxw-empty">报告尚未生成（终态后由服务端产出）。</p>
        </div>

        <!-- 产物 -->
        <div v-else class="nxw-pane">
          <div v-for="a in artifacts" :key="a.artifact_id || a.name" class="nxw-file">
            <FileText :size="13" />
            <span class="nxw-fname">{{ a.filename || a.name || a.artifact_id }}</span>
            <span class="nxw-spacer" />
            <span v-if="a.size_bytes" class="nxw-fsize">
              {{ (a.size_bytes / 1024).toFixed(1) }} KB
            </span>
          </div>
          <p v-if="!artifacts.length" class="nxw-empty">本次运行暂无产物登记。</p>
        </div>

        <footer class="nxw-foot">
          <span class="nxw-mono">exit {{ ['running', 'queued', 'cancelling'].includes(run.status) ? '—' : (run.code ?? '—') }}</span>
          <span v-if="['running', 'queued', 'cancelling'].includes(run.status)">运行中退出码未定，不显示 0</span>
          <span class="nxw-spacer" />
          <span class="nxw-mono">Worker · {{ run.job_id }}</span>
        </footer>
      </section>
    </div>
  </section>

  <section v-else class="nxw nxw-blank">
    <div class="nxw-blank-inner">
      <FlaskConical :size="26" />
      <h3>这个会话还没有实验</h3>
      <p>论文、研究问题、实验与报告都留在这个会话里。切回研究对话描述目标，或在输入框旁选择「准备实验」。</p>
      <SfxButton variant="secondary" size="sm" @click="emit('ask', '')">询问 Nexus 如何开始</SfxButton>
    </div>
  </section>
</template>

<style scoped>
.nxw {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface-canvas);
}

/* ── 头部 ───────────────────────────────── */
.nxw-head {
  flex: 0 0 auto;
  height: 48px;
  padding: 0 var(--space-6);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  border-bottom: 1px solid var(--border-default);
  background: var(--surface-panel);
}
.nxw-elapsed { font-family: var(--font-mono); font-size: var(--ui-sm-size); color: var(--text-muted); font-variant-numeric: tabular-nums; }
.nxw-spacer { flex: 1; }
.nxw-st {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: var(--caption-size); font-weight: 500;
  border: 1px solid var(--border-default); border-radius: var(--radius-full);
  padding: 2px 9px 2px 7px; background: var(--surface-panel);
}
.nxw-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--text-disabled); }
.nxw-st.is-run { color: var(--nexus-accent); border-color: var(--nexus-accent-line); background: var(--nexus-accent-soft); }
.nxw-st.is-run .nxw-dot { background: var(--nexus-accent); }
.nxw-st.is-ok { color: var(--green-700); border-color: var(--green-300); background: var(--green-100); }
.nxw-st.is-ok .nxw-dot { background: var(--green-700); }
.nxw-st.is-err { color: var(--red-700); border-color: var(--red-300); background: var(--red-100); }
.nxw-st.is-err .nxw-dot { background: var(--red-700); }
.nxw-runsel { display: inline-flex; align-items: center; gap: 6px; }
.nxw-runsel-label { font-size: var(--caption-size); color: var(--text-muted); }
.nxw-select {
  height: 26px; border: 1px solid var(--border-default); border-radius: var(--radius-xs);
  background: var(--surface-panel); font-size: var(--ui-sm-size); color: var(--text-secondary);
  padding: 0 6px; max-width: 168px;
}

/* ── 阶段条：单行 20px，不抢高度 ─────────── */
.nxw-stagebar {
  flex: 0 0 auto;
  display: flex; align-items: center;
  padding: 10px var(--space-6);
  background: var(--surface-panel);
  border-bottom: 1px solid var(--border-subtle);
}
.nxw-stg {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: var(--caption-size); color: var(--text-disabled); white-space: nowrap;
}
.nxw-stgdot { width: 5px; height: 5px; border-radius: 50%; background: var(--border-strong); }
.nxw-stg.is-done { color: var(--text-secondary); }
.nxw-stg.is-done .nxw-stgdot { background: var(--green-700); }
.nxw-stg.is-current { color: var(--nexus-accent); font-weight: 600; }
.nxw-stg.is-current .nxw-stgdot { background: var(--nexus-accent); box-shadow: 0 0 0 3px var(--nexus-accent-soft); }
.nxw-stg.is-failed { color: var(--red-700); }
.nxw-stg.is-failed .nxw-stgdot { background: var(--red-700); }
.nxw-stg.is-skipped .nxw-stgdot {
  background: transparent; border: 1px dashed var(--border-strong); width: 7px; height: 7px;
}
.nxw-stgnote { font-size: 10px; color: var(--text-disabled); }
.nxw-stgline { flex: 1; height: 1px; background: var(--border-default); margin: 0 9px; min-width: 12px; }
.nxw-stgline.is-done { background: var(--green-300); }
.nxw-stagenotes {
  flex: 0 0 auto;
  margin: 0; padding: 6px var(--space-6);
  font-size: var(--caption-size); color: var(--text-muted);
  background: var(--surface-soft); border-bottom: 1px solid var(--border-default);
}

/* ── 主体 ───────────────────────────────── */
.nxw-body {
  flex: 1; min-height: 0;
  display: grid; grid-template-columns: 320px 1fr;
}
.nxw-side {
  border-right: 1px solid var(--border-default);
  overflow-y: auto; padding-bottom: var(--space-5);
  background: var(--surface-panel);
}
.nxw-cap {
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--text-disabled); font-weight: 600;
  padding: var(--space-3) var(--space-4) 6px;
}
.nxw-kv {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 5px var(--space-4); font-size: var(--ui-sm-size);
  border-bottom: 1px solid var(--border-subtle);
}
.nxw-kv span { color: var(--text-muted); }
.nxw-kv b {
  font-family: var(--font-mono); font-weight: 400; font-size: var(--caption-size);
  color: var(--text-primary); word-break: break-all; text-align: right; max-width: 62%;
}
.nxw-steps { list-style: none; margin: 0; padding: 0 var(--space-4); }
.nxw-step { position: relative; padding: 0 0 var(--space-3) 18px; }
.nxw-step::before {
  content: ''; position: absolute; left: 2px; top: 10px; bottom: -4px;
  width: 1px; background: var(--border-default);
}
.nxw-step:last-child::before { display: none; }
.nxw-step::after {
  content: ''; position: absolute; left: -1px; top: 6px;
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--surface-panel); border: 1.5px solid var(--border-strong);
}
.nxw-step.is-ok::after { background: var(--green-700); border-color: var(--green-700); }
.nxw-step.is-err::after { background: var(--red-700); border-color: var(--red-700); }
.nxw-step.is-run::after { border-color: var(--nexus-accent); box-shadow: 0 0 0 3px var(--nexus-accent-soft); }
.nxw-cmd {
  font-family: var(--font-mono); font-size: var(--caption-size);
  color: var(--text-primary); line-height: 1.5; word-break: break-all;
}
.nxw-meta {
  display: flex; gap: 10px; margin-top: 3px;
  font-size: 10.5px; font-family: var(--font-mono); color: var(--text-disabled);
  font-variant-numeric: tabular-nums;
}
.nxw-ex { }
.nxw-runbadge { color: var(--nexus-accent); }
.nxw-statetext { }
.nxw-tail {
  margin-top: 6px; padding: 6px 8px;
  background: var(--surface-soft); border: 1px solid var(--border-default);
  border-radius: var(--radius-xs);
  font-family: var(--font-mono); font-size: 10.5px; line-height: 1.6;
  color: var(--text-secondary); white-space: pre-wrap; word-break: break-all;
}

/* ── 输出区 ─────────────────────────────── */
.nxw-out { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
.nxw-tabs {
  flex: 0 0 auto; display: flex; align-items: center; gap: 2px;
  padding: 8px var(--space-4) 0; border-bottom: 1px solid var(--border-default);
  background: var(--surface-panel);
}
.nxw-tab {
  font-size: var(--ui-sm-size); color: var(--text-muted);
  padding: 5px 10px 8px; border-bottom: 2px solid transparent; cursor: pointer;
}
.nxw-tab.is-on { color: var(--text-primary); font-weight: 600; border-bottom-color: var(--nexus-accent); }
.nxw-tabn { font-family: var(--font-mono); font-size: 10px; color: var(--text-disabled); margin-left: 4px; }
.nxw-logsrc { font-size: var(--caption-size); color: var(--text-muted); padding-bottom: 6px; }

.nxw-term {
  flex: 1; min-height: 0; overflow: auto;
  background: var(--code-bg); padding: var(--space-3) var(--space-4);
}
.nxw-log {
  margin: 0; font-family: var(--font-mono); font-size: var(--caption-size);
  line-height: 1.75; color: var(--code-text); white-space: pre-wrap; word-break: break-all;
}
.nxw-term.is-empty { background: var(--surface-panel); display: grid; place-items: center; }

.nxw-pane {
  flex: 1; min-height: 0; overflow: auto;
  padding: var(--space-4) var(--space-5); background: var(--surface-panel);
}
.nxw-verdict {
  display: flex; align-items: baseline; gap: var(--space-3);
  padding: var(--space-3) var(--space-4); border-radius: var(--radius-sm);
  border: 1px solid var(--green-300); background: var(--green-100); margin-bottom: var(--space-4);
}
.nxw-verdict.is-fail { border-color: var(--red-300); background: var(--red-100); }
.nxw-verdict-label { font-size: var(--caption-size); color: var(--text-muted); }
.nxw-verdict b { font-family: var(--font-mono); font-size: 18px; color: var(--green-700); }
.nxw-verdict.is-fail b { color: var(--red-700); }
.nxw-verdict-src { margin-left: auto; font-size: 10.5px; color: var(--text-muted); font-family: var(--font-mono); }
.nxw-table { width: 100%; border-collapse: collapse; font-size: var(--ui-sm-size); }
.nxw-table th {
  text-align: left; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--text-disabled); font-weight: 600; padding: 0 10px 7px 0;
  border-bottom: 1px solid var(--border-strong);
}
.nxw-table td { padding: 7px 10px 7px 0; border-bottom: 1px solid var(--border-subtle); color: var(--text-secondary); }
.nxw-table td.is-num { text-align: right; font-family: var(--font-mono); color: var(--text-primary); font-variant-numeric: tabular-nums; }
.nxw-na {
  display: flex; align-items: center; gap: var(--space-2);
  margin-top: var(--space-4); padding: var(--space-4);
  border: 1px dashed var(--border-strong); border-radius: var(--radius-sm);
  background: var(--surface-soft);
  font-size: var(--caption-size); color: var(--text-muted);
}
.nxw-file {
  display: flex; align-items: center; gap: var(--space-2);
  padding: 8px 0; border-bottom: 1px solid var(--border-subtle); font-size: var(--ui-sm-size);
}
.nxw-fname { font-family: var(--font-mono); font-size: var(--caption-size); color: var(--text-primary); }
.nxw-fsize { font-family: var(--font-mono); font-size: 10.5px; color: var(--text-disabled); }
.nxw-empty { font-size: var(--ui-sm-size); color: var(--text-disabled); padding: var(--space-4); text-align: center; }
.nxw-err {
  display: flex; align-items: center; gap: 6px; margin-top: var(--space-3);
  font-size: var(--caption-size); color: var(--red-700);
}

.nxw-foot {
  flex: 0 0 auto; display: flex; align-items: center; gap: var(--space-3);
  padding: 6px var(--space-4); font-size: var(--caption-size); color: var(--text-muted);
  background: var(--surface-soft); border-top: 1px solid var(--border-default);
}
.nxw-mono { font-family: var(--font-mono); font-size: 10.5px; }

/* ── 空态 ───────────────────────────────── */
.nxw-blank { display: grid; place-items: center; }
.nxw-blank-inner { text-align: center; max-width: 420px; color: var(--text-muted); }
.nxw-blank-inner h3 { font-size: var(--title-3-size); color: var(--text-primary); margin: var(--space-3) 0 6px; }
.nxw-blank-inner p { font-size: var(--ui-sm-size); line-height: 1.7; margin-bottom: var(--space-4); }
</style>
