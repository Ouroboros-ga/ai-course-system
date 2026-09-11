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
  ShieldCheck,
  Square,
  TriangleAlert
} from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'
import NexusComparePanel from './NexusComparePanel.vue'
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
  cancelling: { type: Boolean, default: false },
  /** NX-LB5：当前 run 的备注（追加式，升序） */
  notes: { type: Array, default: () => [] },
  /** NX-LB1：preset 投影（参数白名单/预算/指标基线的唯一来源），无则 null */
  preset: { type: Object, default: null },
  /** 备注提交中（父调 API） */
  noting: { type: Boolean, default: false },
  /** T5 Ask/Auto：Ask 下禁用新启动/复跑（服务端同样拒绝，双保险） */
  executionMode: { type: String, default: 'ask' },
  /** F8：当前对照详情（public_compare_view）；无对照时 null */
  compare: { type: Object, default: null },
  /** F8：本会话对照列表（摘要），多对照时可切换 */
  compares: { type: Array, default: () => [] },
  /** F8：关联提交中（父调 API） */
  linking: { type: Boolean, default: false },
})

const emit = defineEmits(['switch', 'cancel', 'ask', 'analyze', 'rerun', 'rename', 'add-note',
  'report', 'formats', 'clean-verify', 'resume', 'interrupt-op',
  'compare-select', 'compare-link', 'compare-cancel'])

const tab = ref('logs')

const active = computed(() => props.runs.find((r) => r.id === props.activeId) || props.runs[0] || null)
const run = computed(() => active.value?.run || null)
const rail = computed(() => (run.value ? reproStageRail(run.value) : []))
const stageNotes = computed(() => (run.value ? reproStageNotes(run.value) : ''))
const elapsed = computed(() => (run.value ? reproElapsed(run.value) : ''))
const cancellable = computed(() => reproCancellable(run.value))

const TABS = [
  { key: 'logs', label: '日志' },
  { key: 'metrics', label: '指标' },
  { key: 'artifacts', label: '产物' },
  { key: 'notes', label: '备注' },
  { key: 'compare', label: '对照' }
]

/* F8：传给对照面板的"当前 run" —— run_id 才是关联用的真身（job_id 只用于取消/报告） */
const activeRunRef = computed(() => ({
  id: active.value?.id || '',
  runId: active.value?.run?.run_id || '',
  name: active.value?.name || '',
}))

/* ── 重命名（NX-LB1）：就地编辑，父组件负责调 PATCH 与乐观锁冲突处理 ──
   真实请求在父组件；这里只管输入与反馈，失败由父通过 onError 回传。 */
const renaming = ref(false)
const renameDraft = ref('')
const renameErr = ref('')
const renameBusy = ref(false)

function startRename() {
  renameDraft.value = active.value?.name || ''
  renameErr.value = ''
  renaming.value = true
}
function cancelRename() {
  renaming.value = false
  renameErr.value = ''
  renameBusy.value = false
}
function submitRename() {
  const title = renameDraft.value.trim()
  if (title.length > 120) {
    renameErr.value = '最多 120 个字符'
    return
  }
  renameBusy.value = true
  renameErr.value = ''
  emit('rename', {
    id: active.value?.id,
    title,
    onError: (msg) => {
      renameBusy.value = false
      renameErr.value = msg
    },
    onDone: () => {
      renameBusy.value = false
      renaming.value = false
    }
  })
}

/* ── 备注（NX-LB5）：追加式，不提供编辑/删除；author_kind 由服务端判定 ── */
const noteDraft = ref('')
const NOTE_MAX = 4000

function submitNote() {
  const content = noteDraft.value.trim()
  if (!content) return
  emit('add-note', {
    content,
    onError: () => {},
    onDone: () => {
      noteDraft.value = ''
    }
  })
}

function noteTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return Number.isNaN(d.getTime())
    ? String(ts)
    : `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/* preset 投影：参数白名单只来自服务端，前端不硬编码参数列表 */
const presetRows = computed(() => {
  const p = props.preset
  if (!p) return []
  const rows = []
  const push = (k, v) => {
    if (v === undefined || v === null || v === '') return
    rows.push({ k, v: typeof v === 'object' ? JSON.stringify(v) : String(v) })
  }
  push('preset', p.display_name || p.preset_id)
  push('论文', p.paper_title)
  push('预算', p.budget?.estimated_minutes != null ? `${p.budget.estimated_minutes} 分钟` : null)
  push('步数上限', p.budget?.max_steps)
  push('CPU 可用', p.budget?.cpu_friendly === true ? '是' : p.budget?.cpu_friendly === false ? '否' : null)
  push('指标', p.metric?.name || p.metrics?.name)
  push('基线', p.metric?.baseline ?? p.metrics?.baseline)
  push('容差', p.metric?.tolerance ?? p.metrics?.tolerance)
  return rows
})

const presetParams = computed(() => {
  const p = props.preset
  if (!p) return []
  const schema = p.parameters || p.parameter_schema || p.params
  if (!schema) return []
  if (Array.isArray(schema)) return schema
  return Object.entries(schema).map(([name, def]) => ({
    name,
    type: def?.type || def?.kind || '',
    default: def?.default ?? def?.default_value,
    enum: def?.enum || def?.choices,
    min: def?.min,
    max: def?.max
  }))
})

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
  if (withLog.length) return withLog[withLog.length - 1].log_tail
  // T5：自主 run 日志尾在 attempts 上。
  const tailed = (run.value.attempts || []).filter((a) => a.log_tail)
  return tailed.length ? tailed[tailed.length - 1].log_tail : ''
})

/** T5：自主 run（无 Worker job）：attempt 即步骤，阶段条不适用。 */
const isAutonomous = computed(() => {
  const r = run.value
  if (!r) return false
  return r.provider === 'autonomous' || (!r.job_id && !!(r.run_id || r.runId))
})

const isAsk = computed(() => props.executionMode !== 'auto')

/** 配置区只展示 run 记录里真实存在的字段，缺字段显示「未建立」而不是猜值 */
const configRows = computed(() => {
  const r = run.value
  if (!r) return []
  const auto = isAutonomous.value
  return [
    { k: 'preset', v: auto ? '自主实验' : (r.preset_id || '未建立') },
    { k: 'job_id', v: r.job_id || (auto ? '—（直连沙箱）' : '未建立') },
    { k: 'seed', v: r.seedUsed ? '已固定' : '未固定' },
    { k: '步骤', v: auto ? `${(r.attempts || []).length || '—'}` : `${(r.stages || []).length || '—'}` },
    { k: '当前步', v: ['running', 'cancelling'].includes(r.status) ? String(r.currentStep ?? (auto ? (r.attempt_no ?? '—') : '—')) : '—' }
  ]
})

const steps = computed(() => {
  // T5：自主 run 用 attempts 渲染同一形状（编号/命令摘要/退出码/日志尾）。
  if (isAutonomous.value) {
    return (run.value?.attempts || []).map((a) => ({
      index: a.attempt_no,
      command: a.command_summary || '',
      exit_code: a.exit_code,
      duration_s: a.duration_s,
      timed_out: null,
      log_tail: a.log_tail || ''
    }))
  }
  return (run.value?.stages || []).map((s) => ({
    index: s.index,
    command: s.command || '',
    exit_code: s.exit_code,
    duration_s: s.duration_s,
    timed_out: s.timed_out,
    log_tail: s.log_tail || ''
  }))
})

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
/** F1：自主 run 四分量报告（服务端 report 原样展示，不合成单一成功）。 */
const hasAutoReport = computed(() => !!run.value?.autoReport)
/** F3：在途活跃操作及其增量文本（游标缓冲由父组件随轮询推进）。 */
const activeOpId = computed(() => run.value?.activeOperation || '')
const activeOpText = computed(() => {
  const id = activeOpId.value
  if (!id) return ''
  return (run.value?.opLogText || {})[id] || ''
})

/** T6：自主 run 终态（succeeded/failed）且尚未生成报告 → 可生成。 */
const isReportable = computed(() => {
  const r = run.value
  if (!r) return false
  const auto = isAutonomous.value
  if (!auto) return false
  if (!['succeeded', 'failed'].includes(r.status)) return false
  return !r.reportRequested
})
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

      <!-- NX-LB1 重命名：就地编辑；提交走 PATCH /runs/{id}（乐观锁）。
           改名只改显示名，不改变执行 hash 或运行配置——提示写在输入框里，别让用户误会。 -->
      <template v-if="!renaming">
        <SfxButton
          variant="tertiary"
          size="sm"
          title="重命名本次运行（仅改显示名，不改变执行配置）"
          @click="startRename"
        >重命名</SfxButton>
      </template>
      <span v-else class="nxw-rename">
        <input
          v-model="renameDraft"
          class="nxw-rename-input"
          maxlength="120"
          placeholder="留空恢复默认名"
          @keydown.enter.prevent="submitRename"
          @keydown.esc.prevent="cancelRename"
        />
        <SfxButton variant="secondary" size="sm" :loading="renameBusy" @click="submitRename">保存</SfxButton>
        <SfxButton variant="tertiary" size="sm" :disabled="renameBusy" @click="cancelRename">取消</SfxButton>
      </span>

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
      <!-- F2：运行中自主 run 可认领恢复（对账在途意图后继续；Ask 禁用，服务端 403）。 -->
      <SfxButton
        v-if="isAutonomous && ['running', 'cancelling'].includes(run?.status)"
        variant="tertiary"
        size="sm"
        :loading="!!run?.resuming"
        :disabled="isAsk || !!run?.resuming"
        :title="isAsk ? '恢复认领后可能继续执行，Ask 模式不可用，切换到 Auto 后可用' : '对账在途操作，需继续时后台续跑同一实验'"
        @click="emit('resume', active.id)"
      >
        <template #icon><RotateCw :size="12" /></template>
        继续执行
      </SfxButton>
      <template v-else-if="hasReport">
        <SfxButton variant="primary" size="sm" @click="emit('analyze', active.id)">
          <template #icon><FlaskConical :size="13" /></template>
          分析本次结果
        </SfxButton>
        <!-- T5 Ask：禁止新启动/复跑（服务端同样 403，双保险；General 无此面板）。 -->
        <SfxButton
          variant="secondary"
          size="sm"
          :disabled="isAsk"
          :title="isAsk ? 'Ask 模式不运行实验，切换到 Auto 后可用' : '复制冻结配置建新提案，重新审批后运行'"
          @click="emit('rerun', active.id)"
        >
          <template #icon><RotateCw :size="13" /></template>
          调整方案再运行
        </SfxButton>
      </template>
      <!-- T6 自主 run：终态后可生成报告＋配方（确定性拼装，不经 LLM；
           产物关联本 run，可下载；落盘后回收工作区。Ask 下禁用（回收涉及
           沙箱调用，服务端同样拒绝），切 Auto 后可用。 -->
      <template v-else-if="isReportable">
        <SfxButton
          variant="primary"
          size="sm"
          :loading="!!run?.reportRequested"
          :disabled="isAsk"
          :title="isAsk ? 'Ask 模式不运行实验相关操作，切换到 Auto 后可用' : '生成确定性报告与可重复配方（产物可下载）'"
          @click="emit('report', active.id)"
        >
          <template #icon><FileText :size="13" /></template>
          生成报告
        </SfxButton>
      </template>
      <!-- T5：执行器失联但运行未终止（reconciling），如实标注，不冒称失败。 -->
      <span v-if="run?.reconciling" class="nxw-note" title="执行器不可达，显示登记快照；运行未终止，恢复后继续">
        对账中
      </span>
      <!-- F2：恢复状态只读展示（UI 不分支新枚举）。 -->
      <span v-if="run?.recoveryStatus" class="nxw-note" :title="run?.completionReason || ''">
        恢复：{{ run.recoveryStatus === 'recovering' ? '认领中' : run.recoveryStatus === 'recovered' ? '已接续' : run.recoveryStatus === 'unrecoverable' ? '不可自动恢复' : run.recoveryStatus }}
      </span>
    </header>

    <!-- 阶段条：六段固定轨道，状态来自 Worker 真实 stage_events。
         T5：自主 run 无 Worker 轨道时隐藏（attempt 列表才是真相源）。 -->
    <div v-if="!isAutonomous" class="nxw-stagebar" role="list" aria-label="执行阶段">
      <template v-for="(st, i) in rail" :key="st.stage">
        <div v-if="i" class="nxw-stgline" :class="{ 'is-done': st.state === 'done' }" />
        <div class="nxw-stg" :class="`is-${st.state}`" role="listitem" :title="st.note || st.label">
          <i class="nxw-stgdot" />
          <span>{{ st.label }}</span>
          <span v-if="st.state === 'skipped'" class="nxw-stgnote">不适用</span>
        </div>
      </template>
    </div>
    <p v-if="stageNotes" class="nxw-stagenotes">{{ stageNotes }}</p>

    <!-- 主体：左配置/步骤 · 右输出 -->
    <div class="nxw-body">
      <aside class="nxw-side">
        <div class="nxw-cap">运行配置 · 只读</div>
        <div v-for="row in configRows" :key="row.k" class="nxw-kv">
          <span>{{ row.k }}</span>
          <b>{{ row.v }}</b>
        </div>

        <!-- NX-LB1 preset 投影：参数白名单/默认值/预算/指标基线的唯一来源。
             前端禁止硬编码参数列表；服务端没给就整块不渲染，不猜。 -->
        <template v-if="presetRows.length">
          <div class="nxw-cap">预设 · 只读</div>
          <div v-for="row in presetRows" :key="row.k" class="nxw-kv">
            <span>{{ row.k }}</span>
            <b>{{ row.v }}</b>
          </div>
        </template>
        <template v-if="presetParams.length">
          <div class="nxw-cap">可改参数 · {{ presetParams.length }}</div>
          <div v-for="p in presetParams" :key="p.name" class="nxw-kv">
            <span>{{ p.name }}</span>
            <b>{{ p.default === undefined || p.default === null || p.default === '' ? '—' : p.default }}</b>
          </div>
          <p class="nxw-note">
            仅白名单内参数可改，范围与默认值由服务端投影；越界会被拒绝。
          </p>
        </template>

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
        <p v-if="!steps.length" class="nxw-empty">{{ isAutonomous ? '尚无尝试记录（执行器尚未回传）。' : '尚无步骤记录（作业未开始或 Worker 未返回）。' }}</p>
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
            <b v-else-if="t.key === 'notes' && notes.length" class="nxw-tabn">{{ notes.length }}</b>
            <b v-else-if="t.key === 'compare' && compares.length" class="nxw-tabn">{{ compares.length }}</b>
          </span>
          <span class="nxw-spacer" />
          <span v-if="tab === 'logs' && logText" class="nxw-logsrc">{{ reproLogSource(run) }}</span>
        </div>

        <!-- 日志：唯一深色语境 -->
        <div v-if="tab === 'logs'" class="nxw-term" :class="{ 'is-empty': !logText && !activeOpId }">
          <!-- F3：在途活跃操作（增量输出＋单命令中断；整体取消仍走头部取消）。 -->
          <div v-if="activeOpId" class="nxw-activeop">
            <div class="nxw-activeop-head">
              <span class="nxw-mono">{{ activeOpId }}</span>
              <span class="nxw-runbadge">进行中</span>
              <span class="nxw-spacer" />
              <SfxButton
                variant="tertiary"
                size="sm"
                :loading="!!run?.interrupting"
                :disabled="isAsk || !!run?.interrupting"
                :title="isAsk ? '中断后可能继续执行，Ask 模式不可用，切换到 Auto 后可用' : '只停止该命令（确认停止后可继续排错）'"
                @click="emit('interrupt-op', { id: active.id, operationId: activeOpId })"
              >
                中断该命令
              </SfxButton>
            </div>
            <pre v-if="activeOpText" class="nxw-log">{{ activeOpText }}</pre>
            <p v-else class="nxw-empty">暂无增量输出（长命令输出可能缓冲，见说明）。</p>
          </div>
          <pre v-if="logText" class="nxw-log">{{ logText }}</pre>
          <p v-else-if="!activeOpId" class="nxw-empty">暂无日志输出。</p>
        </div>

        <!-- 指标：只渲染服务端 report，绝不自行计算 -->
        <div v-else-if="tab === 'metrics'" class="nxw-pane">
          <!-- F1：自主 run 四分量分别展示（环境/目标/指标/干净各自成立）。 -->
          <div v-if="hasAutoReport && isAutonomous" class="nxw-autoreport">
            <div class="nxw-cap">自主实验结论 · 四分量（源：POST /nexus/repro/runs/{id}/report）</div>
            <div class="nxw-kv"><span>环境就绪</span><b>{{ run.autoReport.environment_ready == null ? '未评估' : (run.autoReport.environment_ready ? '是' : '否') }}</b></div>
            <div class="nxw-kv"><span>目标完成</span><b>{{ run.autoReport.execution_succeeded == null ? '未评估' : (run.autoReport.execution_succeeded ? '是' : '否') }}</b></div>
            <div class="nxw-kv"><span>指标</span><b>{{ run.autoReport.metric_verdict || '未评估' }}</b></div>
            <div class="nxw-kv"><span>干净验证</span><b>{{ run.autoReport.clean_verification || '未验证' }}</b></div>
            <p v-if="run.autoReport.legacy_target" class="nxw-note">目标证据为历史兼容口径，不得当作新规则目标证据。</p>
            <p v-if="run.autoReport.metric_note" class="nxw-note">{{ run.autoReport.metric_note }}</p>
            <p v-if="run.autoReport.clean_note" class="nxw-note">{{ run.autoReport.clean_note }}</p>
          </div>
          <div v-if="hasReport" class="nxw-verdict" :class="run.verdict === 'PASS' ? 'is-pass' : 'is-fail'">
            <span class="nxw-verdict-label">指标判定</span>
            <b>{{ run.verdict }}</b>
            <span class="nxw-verdict-src">源：GET /nexus/repro/jobs/{id}/report</span>
          </div>
          <!-- SR6 正式输出：报告已生成后可导出 Word/LaTeX（纯渲染，Ask 可用）；
               干净验证重放进沙箱，只在 Auto 下可用（服务端同样 403）。 -->
          <div v-if="hasReport && isAutonomous" class="nxw-formats">
            <SfxButton
              variant="secondary"
              size="sm"
              :loading="!!run?.formatsRequested"
              :disabled="!!run?.formatsRequested"
              title="导出正式 Word（.docx，可编辑）与 LaTeX（main.tex）产物，可下载"
              @click="emit('formats', active.id)"
            >
              <template #icon><FileText :size="13" /></template>
              导出 Word/LaTeX
            </SfxButton>
            <SfxButton
              variant="secondary"
              size="sm"
              :loading="run?.cleanStatus === 'verifying'"
              :disabled="isAsk || run?.cleanStatus === 'verifying'"
              :title="isAsk ? '干净验证重放进沙箱，Ask 模式不可用，切换到 Auto 后可用' : '在全新沙箱重放冻结配方，比对退出码（结论幂等）'"
              @click="emit('clean-verify', active.id)"
            >
              <template #icon><ShieldCheck :size="13" /></template>
              干净验证
            </SfxButton>
            <span v-if="run?.cleanStatus" class="nxw-note">干净验证：{{ run.cleanStatus === 'verifying' ? '运行中' : run.cleanStatus }}</span>
            <!-- F9：冻结配方身份（只读展示；空=未冻结/历史未验证，不反推执行事实）。 -->
            <span v-if="run?.recipeHash" class="nxw-note">配方：{{ String(run.recipeHash).slice(0, 12) }} · {{ run.recipeStatus || '未知状态' }}</span>
            <span v-else class="nxw-note">配方：未冻结（历史未验证）</span>
            <!-- F6：文档作业身份＋分格式引擎/状态（只读展示，源：服务端作业视图）。 -->
            <span v-if="run?.formatsJobId" class="nxw-note">文档作业：{{ run.formatsJobId }} · {{ run.formatsJobStatus || '—' }}</span>
            <span v-if="run?.formatsByKind?.word" class="nxw-note">Word：{{ run.formatsByKind.word.status || '—' }}（{{ run.formatsByKind.word.engine || '未知引擎' }}）</span>
            <span v-if="run?.formatsByKind?.latex" class="nxw-note">LaTeX：{{ run.formatsByKind.latex.status || '—' }}（{{ run.formatsByKind.latex.engine || '未知引擎' }}）</span>
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

        <!-- 备注（NX-LB5）：追加式，不提供编辑/删除；author_kind 由服务端判定。
             Agent 备注只是解释或建议，不改日志/指标/PASS-FAIL —— 标签里写清楚。 -->
        <div v-else-if="tab === 'notes'" class="nxw-pane">
          <div v-for="n in notes" :key="n.note_id || n.created_at" class="nxw-note-row">
            <span class="nxw-note-who" :class="n.author_kind === 'agent' ? 'is-agent' : 'is-me'">
              {{ n.author_kind === 'agent' ? 'Nexus' : '我' }}
            </span>
            <div class="nxw-note-body">
              <p>{{ n.content }}</p>
              <span class="nxw-note-tm">
                {{ noteTime(n.created_at) }}
                <template v-if="n.author_kind === 'agent'"> · 解释或建议，不改结果</template>
              </span>
            </div>
          </div>
          <p v-if="!notes.length" class="nxw-empty">本次运行还没有备注。</p>

          <div class="nxw-note-add">
            <textarea
              v-model="noteDraft"
              class="nxw-note-input"
              rows="2"
              :maxlength="NOTE_MAX"
              placeholder="记一条备注（例如：为什么改这个参数）"
            />
            <div class="nxw-note-act">
              <span class="nxw-note-count">{{ noteDraft.length }} / {{ NOTE_MAX }}</span>
              <span class="nxw-spacer" />
              <SfxButton
                variant="secondary"
                size="sm"
                :disabled="!noteDraft.trim() || noting"
                :loading="noting"
                @click="submitNote"
              >添加备注</SfxButton>
            </div>
          </div>
        </div>

        <!-- F8 受控对照：跨 run 的受控比较视图。只关联、不执行；
             结论只有 descriptive_ready / incomplete，界面只并列实测、不做优劣判定。 -->
        <div v-else-if="tab === 'compare'" class="nxw-pane nxcmp-host">
          <NexusComparePanel
            :compare="compare"
            :compares="compares"
            :active-run="activeRunRef"
            :linking="linking"
            @select="(id) => emit('compare-select', id)"
            @link="(payload) => emit('compare-link', payload)"
            @cancel="(id) => emit('compare-cancel', id)"
          />
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
  transition:
    color var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out);
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

/* 重命名就地编辑 */
.nxw-rename { display: inline-flex; align-items: center; gap: 6px; }
.nxw-rename-input {
  width: 230px; height: 28px; padding: 0 10px;
  border: 1px solid var(--nexus-accent); border-radius: 4px;
  background: var(--surface-panel); color: var(--text-primary);
  font-family: var(--font-sans); font-size: 12.5px; outline: none;
}
.nxw-note {
  margin: 6px 0 0; font-size: 10.5px; line-height: 1.6; color: var(--text-disabled);
}

/* SR6 正式输出：指标判定下的 Word/LaTeX 导出与干净验证动作行 */
.nxw-formats { display: flex; align-items: center; gap: 8px; margin: 10px 0; flex-wrap: wrap; }

/* 备注（NX-LB5） */
.nxw-note-row { display: grid; grid-template-columns: 52px 1fr; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--border-default); }
.nxw-note-who {
  font-family: var(--font-mono); font-size: 9.5px; height: fit-content;
  padding: 1px 6px; border-radius: 3px; text-align: center;
}
.nxw-note-who.is-me { color: var(--nexus-accent); background: var(--nexus-accent-soft); }
.nxw-note-who.is-agent { color: #8a6a1f; background: #fdf6e3; }
.nxw-note-body p { font-size: 12px; line-height: 1.75; color: var(--text-secondary); white-space: pre-wrap; word-break: break-word; }
.nxw-note-tm { display: block; margin-top: 4px; font-family: var(--font-mono); font-size: 9.5px; color: var(--text-disabled); }
.nxw-note-add { margin-top: 12px; border-top: 1px solid var(--border-default); padding-top: 12px; }
.nxw-note-input {
  width: 100%; padding: 8px 10px; resize: vertical;
  border: 1px solid var(--border-default); border-radius: 4px;
  background: var(--surface-canvas); color: var(--text-primary);
  font-family: var(--font-sans); font-size: 12px; line-height: 1.7; outline: none;
}
.nxw-note-input:focus { border-color: var(--nexus-accent); }
.nxw-note-act { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.nxw-note-count { font-family: var(--font-mono); font-size: 10px; color: var(--text-disabled); font-variant-numeric: tabular-nums; }
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
