<script setup>
/**
 * F8 受控对照面板（工作台「对照」视图）
 *
 * 定位：同一实验问题下两个及以上明确配置的**受控比较**。
 * 与 F5「探索 A → 干净 B」不同（那是复现），也与发版 A/B 不同（那是发布）。
 *
 * 硬规则（与服务端 experiment_compare.py 一致，前端不得自我放宽）：
 * - 对照**不执行任何东西**：只建规格、关联终态运行、并列报告。执行仍走既有批准/run 通道；
 * - 结论只有两种：descriptive_ready / incomplete。**界面不做任何优劣判定**——只并列实测，不比较谁好；
 * - 失败组如实并列，不隐藏、不置灰；指标取不到就显示缺失原因，不填 0、不画占位；
 * - 运行成败沿用系统绿红（--green-700 / --red-700），但**对照结论刻意不用绿**——
 *   descriptive_ready 只表示"可以并列了"，不是"谁赢了"。
 *
 * 取数全在父组件（NexusPage），本组件只渲染与 emit，与工作台既有约定一致。
 * 设计依据：docs/phase1/2026-09-10_NexusLab_F8受控对照_设计板_v2.html
 */
import { computed } from 'vue'
import SfxButton from '@/app/ui/SfxButton.vue'

const props = defineProps({
  /** 对照详情（public_compare_view）；无对照时为 null */
  compare: { type: Object, default: null },
  /** 本会话对照列表（摘要），用于多对照时切换 */
  compares: { type: Array, default: () => [] },
  /** 当前选中的 run（用于"关联当前 run"），形如 { id, runId, name } */
  activeRun: { type: Object, default: null },
  /** 关联提交中（父调 API） */
  linking: { type: Boolean, default: false },
})

const emit = defineEmits(['select', 'link', 'cancel'])

const report = computed(() => props.compare?.report || null)
const rows = computed(() => report.value?.rows || [])
const arms = computed(() => props.compare?.arms || [])
const common = computed(() => props.compare?.common || report.value?.common || {})
const allowed = computed(() => props.compare?.allowed_varied || report.value?.allowed_varied || [])

/** 已关联组数 / 总组数——驱动头部进度线 */
const linkedCount = computed(() => rows.value.filter((r) => r.run_id).length)
const progress = computed(() =>
  rows.value.length ? Math.round((linkedCount.value / rows.value.length) * 100) : 0)

const statusLabel = computed(() => {
  switch (props.compare?.status) {
    case 'open': return 'OPEN'
    case 'running': return 'RUNNING'
    case 'cancelled': return 'CANCELLED'
    default: return props.compare?.status ? String(props.compare.status).toUpperCase() : '—'
  }
})
const isTerminal = computed(() => props.compare?.status === 'cancelled')

const verdictLabel = computed(() => {
  const v = report.value?.verdict
  if (v === 'descriptive_ready') return 'DESCRIPTIVE_READY'
  if (v === 'incomplete') return 'INCOMPLETE'
  return '—'
})

const notes = computed(() => report.value?.comparability_notes || [])
const reasons = computed(() => report.value?.verdict_reasons || [])
/** 免责文案直接取服务端常量，前端不改写、不本地化 */
const disclaimer = computed(() =>
  report.value?.significance ||
  '本对照只做描述性并列；未设计统计检验、重复次数不足，不声称任何显著提升，结论以各组实测与缺失说明为准。')

const primaryKey = computed(() => common.value?.metric_policy?.primary || '')
const primaryDir = computed(() => common.value?.metric_policy?.direction || '')

/**
 * 指标显示：指标政策声明的 primary 优先；未声明或报告里没有该键时，回退第一个实测值。
 * 只取存储报告的实测值——取不到即由调用方显示 metrics_missing，不填 0、不推算。
 */
function metricOf(row) {
  const m = row.metrics
  if (!m || typeof m !== 'object') return null
  const keys = Object.keys(m)
  if (!keys.length) return null
  const primary = primaryKey.value
  if (primary && primary in m) return { key: primary, value: m[primary] }
  return { key: keys[0], value: m[keys[0]] }
}

/** 逐组预计算，避免模板里重复调用 metricOf */
const rowMetrics = computed(() => rows.value.map((r) => metricOf(r)))

function fmtVal(v) {
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(3)
  return v == null ? '—' : String(v)
}

/** 变化参数展示：{lr: 3e-4} → "lr = 3e-4" */
function variedText(row) {
  const v = row.varied_params || {}
  const keys = Object.keys(v)
  if (!keys.length) return '（无变化参数）'
  return keys.map((k) => `${k} = ${fmtVal(v[k])}`).join(' · ')
}

function shortHash(h) {
  const s = String(h || '')
  return s.length > 12 ? `${s.slice(0, 10)}…` : s
}

function isFailed(row) {
  return String(row.run_status || '') === 'failed'
}
function exitClass(row) {
  if (!row.run_id) return 'is-missing'
  return isFailed(row) ? 'is-failed' : 'is-ok'
}

/**
 * 干净验证（干净 B 重放）的显示类：
 * - 有真实结论时按结论着色（failed 用红；passed 用中性色，不画绿色"完成"）；
 * - 空值才落到灰色"不适用"。
 */
function cleanClass(row) {
  const s = String(row.clean_status || '').toLowerCase()
  if (!s) return 'is-missing'
  if (s.includes('fail') || s.includes('mismatch')) return 'is-failed'
  return ''  // passed / 其他真实结论：中性，不暗示"更好"
}

/** 组是否已关联，用于决定渲染"关联"还是结果 */
function linked(row) {
  return !!row.run_id
}

/** 可否关联当前 run：需有对照、未终态、有当前 run 且该组未关联 */
function canLink(row) {
  return !!props.compare && !isTerminal.value && !!props.activeRun?.runId && !linked(row)
}

function linkText(row) {
  if (!props.activeRun?.runId) return '需先选中一个 run'
  return `关联当前 run · ${props.activeRun.name || props.activeRun.runId}`
}
</script>

<template>
  <section class="nxcmp" aria-label="受控对照">
    <!-- ══ 头部：标识 + 状态 + 进度 ══ -->
    <header class="nxcmp-head" :style="{ '--nxcmp-progress': progress + '%' }">
      <div class="nxcmp-head-main">
        <h3 class="nxcmp-title">
          受控对照<span class="nxcmp-dot">·</span><span class="nxcmp-en">CONTROLLED COMPARISON</span>
        </h3>
        <p v-if="compare" class="nxcmp-sub">
          <span class="mono">{{ compare.compare_id }}</span>
          <template v-if="compare.version"> · 规格 <span class="mono">{{ compare.version }}</span></template>
          · 已关联 <span class="mono">{{ linkedCount }}/{{ rows.length }}</span> 组
        </p>
        <p v-else class="nxcmp-sub">本会话尚无受控对照</p>
      </div>

      <div class="nxcmp-head-actions">
        <span class="nxcmp-badge" :class="compare ? `is-${compare.status}` : ''">{{ statusLabel }}</span>
        <SfxButton
          v-if="compare"
          variant="tertiary"
          size="sm"
          :disabled="isTerminal"
          @click="emit('cancel', compare.compare_id)"
        >
          取消对照
        </SfxButton>
      </div>
    </header>

    <!-- ══ 多对照切换 ══ -->
    <div v-if="compares.length > 1" class="nxcmp-picker" role="tablist" aria-label="选择对照">
      <SfxButton
        v-for="c in compares"
        :key="c.compare_id"
        variant="tertiary"
        size="sm"
        :class="{ 'is-current': compare && c.compare_id === compare.compare_id }"
        @click="emit('select', c.compare_id)"
      >
        <span class="mono">{{ c.compare_id }}</span>
      </SfxButton>
    </div>

    <!-- ══ 空态：没有对照 ══ -->
    <div v-if="!compare" class="nxcmp-empty">
      <b>还没有建立对照</b>
      <p>
        在对话里说「对比这两个配置」即可建立受控对照：先声明共同数据（引用＋hash）、
        指标政策与允许变化的参数白名单，再把各组已跑完的终态运行挂靠上来。
      </p>
      <p class="nxcmp-empty-hint">
        对照本身不执行任何东西——它只保证拿来比的两个结果条件一致、配方锁定、失败可见。
      </p>
    </div>

    <template v-else>
      <!-- ══ 对照目标 ══ -->
      <div class="nxcmp-objective">
        <span class="nxcmp-eyebrow">对照目标 / objective</span>
        <p>{{ compare.objective || '—' }}</p>
      </div>

      <!-- ══ 主体：左规格 / 右并列 ══ -->
      <div class="nxcmp-body">
        <aside class="nxcmp-spec">
          <span class="nxcmp-eyebrow">对照规格 · 已锁定</span>

          <div class="nxcmp-block">
            <span class="nxcmp-eyebrow">共同数据</span>
            <dl class="nxcmp-kv">
              <dt>data_ref</dt>
              <dd>{{ common.data_ref || '—' }}</dd>
            </dl>
            <dl class="nxcmp-kv">
              <dt>data_hash</dt>
              <dd class="is-muted">{{ common.data_hash ? shortHash(common.data_hash) : '—' }}</dd>
            </dl>
          </div>

          <div class="nxcmp-block">
            <span class="nxcmp-eyebrow">指标政策</span>
            <dl class="nxcmp-kv">
              <dt>primary</dt>
              <dd>{{ primaryKey || '—' }}</dd>
            </dl>
            <dl class="nxcmp-kv">
              <dt>direction</dt>
              <dd>{{ primaryDir || '—' }}</dd>
            </dl>
          </div>

          <div class="nxcmp-block">
            <span class="nxcmp-eyebrow">允许变化</span>
            <div v-if="allowed.length" class="nxcmp-tags">
              <span v-for="p in allowed" :key="p" class="nxcmp-tag">{{ p }}</span>
            </div>
            <p v-else class="nxcmp-none">（未声明）</p>
          </div>

          <div class="nxcmp-block">
            <span class="nxcmp-eyebrow">预算说明</span>
            <dl class="nxcmp-kv">
              <dt>approval</dt>
              <dd class="is-muted">{{ compare.approval_ref || '（只记不验）' }}</dd>
            </dl>
          </div>
        </aside>

        <div class="nxcmp-report">
          <div class="nxcmp-report-head">
            <span class="nxcmp-eyebrow">并列报告 · 描述性</span>
            <span
              class="nxcmp-verdict"
              :class="report && report.verdict === 'descriptive_ready' ? 'is-ready' : 'is-incomplete'"
            >VERDICT: {{ verdictLabel }}</span>
          </div>

          <div class="nxcmp-arms">
            <article
              v-for="(row, i) in rows"
              :key="row.arm"
              class="nxcmp-arm"
              :class="{
                'is-empty': !linked(row),
                'is-failed': linked(row) && isFailed(row),
                'is-current': linked(row) && !isFailed(row)
              }"
            >
              <div class="nxcmp-arm-name">
                <span>{{ row.arm }}</span>
                <span v-if="linked(row)" class="nxcmp-arm-st" :class="isFailed(row) ? 'is-failed' : 'is-ok'">
                  {{ String(row.run_status || '').toUpperCase() }}
                </span>
                <span v-else class="nxcmp-arm-st is-missing">未关联</span>
              </div>

              <p class="nxcmp-arm-varied">{{ variedText(row) }}</p>
              <p class="nxcmp-arm-recipe">recipe {{ shortHash(row.recipe_hash) }}</p>

              <template v-if="linked(row)">
                <dl class="nxcmp-row"><dt>exit_code</dt><dd :class="exitClass(row)">{{ row.exit_code ?? '—' }}</dd></dl>
                <!-- scope 只显示本组的 hash 值本身。是否"一致"是跨组判断，
                     由服务端 comparability_notes 说话，前端不自行比较、不替它下结论。 -->
                <dl class="nxcmp-row">
                  <dt>scope</dt>
                  <dd :class="row.scope_hash ? '' : 'is-missing'">
                    {{ row.scope_hash ? shortHash(row.scope_hash) : '未记录' }}
                  </dd>
                </dl>
                <dl class="nxcmp-row"><dt>proposal</dt><dd>v{{ row.proposal_version ?? 0 }}</dd></dl>
                <!-- 干净验证：有真实结论就如实显示（失败用红），只有空时才写"不适用"。
                     注意 passed 也不画绿色"完成"——它只说明这次重放与历史一致，不代表更好。 -->
                <dl class="nxcmp-row">
                  <dt>干净验证</dt>
                  <dd :class="cleanClass(row)">{{ row.clean_status || '不适用' }}</dd>
                </dl>

                <div class="nxcmp-metric">
                  <span class="nxcmp-metric-label">
                    {{ rowMetrics[i] ? rowMetrics[i].key : (primaryKey || '实测指标') }}
                    <template v-if="primaryDir"> · {{ primaryDir }}</template>
                  </span>
                  <div v-if="rowMetrics[i]" class="nxcmp-metric-value">{{ fmtVal(rowMetrics[i].value) }}</div>
                  <div v-else class="nxcmp-metric-value is-missing">
                    {{ row.metrics_missing || '存储报告无实测指标' }}
                  </div>
                  <p v-if="row.metric_verdict" class="nxcmp-metric-verdict">判定：{{ row.metric_verdict }}</p>
                </div>
              </template>

              <template v-else>
                <p class="nxcmp-arm-note">
                  <b>等待终态运行</b>
                  需关联一个已跑完、且实际配方 hash 与本组声明一致的 run。未终态、无冻结配方、
                  配方不一致都会被服务端拒绝。
                </p>
                <div class="nxcmp-arm-link">
                  <SfxButton
                    variant="secondary"
                    size="sm"
                    :disabled="!canLink(row)"
                    :loading="linking"
                    :title="canLink(row) ? linkText(row) : '需先选中一个 run'"
                    @click="emit('link', { armName: row.arm, runId: activeRun.runId })"
                  >
                    {{ linkText(row) }}
                  </SfxButton>
                </div>
              </template>
            </article>
          </div>

          <!-- ══ 可比性注记 ══ -->
          <div v-if="notes.length" class="nxcmp-notes">
            <span class="nxcmp-eyebrow">可比性注记 · comparability_notes</span>
            <ul>
              <li v-for="(n, i) in notes" :key="`n${i}`">{{ n }}</li>
            </ul>
          </div>

          <div v-if="reasons.length" class="nxcmp-notes is-reason">
            <span class="nxcmp-eyebrow">结论原因 · verdict_reasons</span>
            <ul>
              <li v-for="(r, i) in reasons" :key="`r${i}`">{{ r }}</li>
            </ul>
          </div>
        </div>
      </div>

      <!-- ══ 常驻免责条：不可关闭 ══ -->
      <div class="nxcmp-disclaimer" role="note">
        <span class="nxcmp-disclaimer-mark" aria-hidden="true">!</span>
        <p>{{ disclaimer }}</p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.nxcmp { display: flex; flex-direction: column; min-height: 0; }

.nxcmp-eyebrow {
  font-family: var(--font-mono); font-size: 10px; font-weight: 500;
  text-transform: uppercase; letter-spacing: .14em; color: var(--text-disabled);
}
.mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }

/* ── 头部：进度线压在分界线上 ─────────────────────────────── */
.nxcmp-head {
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: var(--space-4); padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-strong); position: relative;
}
.nxcmp-head::after {
  content: ""; position: absolute; left: 0; bottom: -1px; height: 2px;
  width: var(--nxcmp-progress, 0%); background: var(--nexus-accent);
  transition: width var(--duration-slow) var(--ease-out);
}
.nxcmp-title {
  margin: 0; font-family: var(--font-mono); font-size: 15px; font-weight: 700;
  letter-spacing: -.01em; color: var(--text-primary);
}
.nxcmp-dot { color: var(--nexus-accent); margin: 0 6px; }
.nxcmp-en { font-size: 10px; font-weight: 500; letter-spacing: .12em; color: var(--text-disabled); }
.nxcmp-sub { margin: 4px 0 0; font-size: 11px; color: var(--text-muted); }
.nxcmp-sub .mono { color: var(--text-secondary); }
.nxcmp-head-actions { display: flex; align-items: center; gap: var(--space-2); flex: none; }

.nxcmp-badge {
  font-family: var(--font-mono); font-size: 10px; font-weight: 500;
  text-transform: uppercase; letter-spacing: .12em;
  padding: 3px 8px; border: 1px solid var(--border-default); border-radius: var(--radius-sm);
  color: var(--text-secondary); background: var(--surface-panel);
}
.nxcmp-badge.is-open, .nxcmp-badge.is-running {
  color: var(--nexus-accent-strong); border-color: var(--nexus-accent-line);
  background: var(--nexus-accent-soft);
}
.nxcmp-badge.is-cancelled { color: var(--text-disabled); border-style: dashed; background: transparent; }

/* ── 多对照切换 ───────────────────────────────────────────── */
.nxcmp-picker { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-3); }
.nxcmp-picker :deep(.sfx-btn) { font-family: var(--font-mono); font-size: 10px; }
.nxcmp-picker :deep(.sfx-btn.is-current) {
  border-color: var(--nexus-accent-line); background: var(--nexus-accent-soft);
  color: var(--nexus-accent-strong);
}

/* ── 空态 ─────────────────────────────────────────────────── */
.nxcmp-empty {
  margin-top: var(--space-5); padding: var(--space-5);
  border: 1px dashed var(--border-strong); border-radius: var(--radius-sm);
  background: var(--surface-canvas);
}
.nxcmp-empty b {
  display: block; font-family: var(--font-mono); font-size: var(--fs-sm, 12px);
  font-weight: 500; color: var(--text-secondary); margin-bottom: var(--space-2);
}
.nxcmp-empty p { margin: 0; font-size: var(--caption-size, 11px); color: var(--text-muted); line-height: 1.8; }
.nxcmp-empty-hint { margin-top: var(--space-2) !important; color: var(--text-disabled) !important; }

/* ── 目标 ─────────────────────────────────────────────────── */
.nxcmp-objective {
  margin-top: var(--space-4); padding: var(--space-3) var(--space-4);
  background: var(--surface-panel); border: 1px solid var(--border-default);
  border-left: 2px solid var(--nexus-accent); border-radius: var(--radius-sm);
}
.nxcmp-objective p {
  margin: 4px 0 0; font-size: 13px; line-height: 1.7; color: var(--text-primary);
}

/* ── 主体：左规格 / 右并列 ────────────────────────────────── */
.nxcmp-body {
  display: grid; grid-template-columns: 280px 1fr; gap: var(--space-4);
  margin-top: var(--space-4); align-items: start;
}

.nxcmp-spec {
  position: relative; padding: var(--space-4);
  background: var(--surface-panel); border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
}
/* 四角括号：标识"规格已锁定" */
.nxcmp-spec::before, .nxcmp-spec::after {
  content: ""; position: absolute; width: 9px; height: 9px; pointer-events: none;
}
.nxcmp-spec::before {
  top: -1px; left: -1px;
  border-top: 1px solid var(--nexus-accent); border-left: 1px solid var(--nexus-accent);
}
.nxcmp-spec::after {
  bottom: -1px; right: -1px;
  border-bottom: 1px solid var(--nexus-accent); border-right: 1px solid var(--nexus-accent);
}

.nxcmp-block { padding: var(--space-2) 0; border-bottom: 1px solid var(--border-subtle); }
.nxcmp-block:first-of-type { padding-top: 0; }
.nxcmp-block:last-of-type { border-bottom: 0; padding-bottom: 0; }
.nxcmp-kv {
  display: grid; grid-template-columns: 74px 1fr; gap: var(--space-2);
  margin: 4px 0 0; align-items: baseline;
}
.nxcmp-kv dt { font-size: 11px; color: var(--text-muted); }
.nxcmp-kv dd {
  margin: 0; font-family: var(--font-mono); font-size: 11px;
  color: var(--text-primary); word-break: break-all;
}
.nxcmp-kv dd.is-muted { color: var(--text-disabled); }

.nxcmp-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.nxcmp-tag {
  font-family: var(--font-mono); font-size: 11px; padding: 1px 7px;
  border: 1px solid var(--nexus-accent-line); border-radius: 2px;
  color: var(--nexus-accent-strong); background: var(--nexus-accent-soft);
}
.nxcmp-none { margin: 4px 0 0; font-size: 11px; color: var(--text-disabled); }

/* ── 并列报告 ─────────────────────────────────────────────── */
.nxcmp-report-head {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: var(--space-3); padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--border-default);
}
/* 结论颜色各归各位：
   - descriptive_ready 中性（只表示"可以并列了"，不是谁赢了，所以不用绿）；
   - incomplete 琥珀（"还没比完"，是待办不是失败，所以不用红）。 */
.nxcmp-verdict { font-family: var(--font-mono); font-size: 11px; font-weight: 500; letter-spacing: .04em; }
.nxcmp-verdict.is-ready { color: var(--text-primary); }
.nxcmp-verdict.is-incomplete { color: var(--amber-700); }

.nxcmp-arms {
  display: grid; gap: var(--space-3); margin-top: var(--space-3);
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
}
.nxcmp-arm {
  padding: var(--space-3) var(--space-4);
  background: var(--surface-panel); border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  transition: border-color var(--duration-normal) var(--ease-out),
              transform var(--duration-normal) var(--ease-out);
}
.nxcmp-arm:hover { border-color: var(--border-strong); transform: translateY(-1px); }
.nxcmp-arm.is-current { border-left: 2px solid var(--green-700); }
.nxcmp-arm.is-failed { border-left: 2px solid var(--red-700); }
.nxcmp-arm.is-empty { border-style: dashed; background: var(--surface-canvas); }

.nxcmp-arm-name {
  display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-2);
  font-family: var(--font-mono); font-size: 12px; font-weight: 700;
  letter-spacing: .04em; text-transform: uppercase; color: var(--text-primary);
}
.nxcmp-arm-st { font-size: 10px; letter-spacing: .1em; }
.nxcmp-arm-st.is-ok { color: var(--green-700); }
.nxcmp-arm-st.is-failed { color: var(--red-700); }
.nxcmp-arm-st.is-missing { color: var(--text-disabled); }

.nxcmp-arm-varied {
  margin: 4px 0 0; font-family: var(--font-mono); font-size: 11px; color: var(--nexus-accent-strong);
}
.nxcmp-arm-recipe { margin: 6px 0 0; font-family: var(--font-mono); font-size: 10px; color: var(--text-disabled); }

.nxcmp-row {
  display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-2);
  padding: 4px 0; border-top: 1px solid var(--border-subtle); font-size: 11px;
}
.nxcmp-row dt { color: var(--text-muted); }
.nxcmp-row dd {
  margin: 0; font-family: var(--font-mono); color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}
.nxcmp-row dd.is-ok { color: var(--green-700); }
.nxcmp-row dd.is-failed { color: var(--red-700); }
.nxcmp-row dd.is-missing { color: var(--text-disabled); font-style: italic; }

.nxcmp-metric { margin-top: var(--space-3); padding-top: var(--space-3); border-top: 1px solid var(--border-strong); }
.nxcmp-metric-label { font-size: 11px; color: var(--text-muted); }
.nxcmp-metric-value {
  font-family: var(--font-mono); font-size: 28px; font-weight: 500;
  font-variant-numeric: tabular-nums; letter-spacing: -.03em; line-height: 1.2;
  color: var(--text-primary); margin-top: 2px;
}
.nxcmp-metric-value.is-missing {
  font-size: 12px; font-style: italic; color: var(--text-disabled);
  letter-spacing: 0; line-height: 1.7; font-weight: 400;
}
.nxcmp-metric-verdict { margin: 4px 0 0; font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); }

.nxcmp-arm-note { margin: var(--space-3) 0 0; font-size: 11px; color: var(--text-muted); line-height: 1.8; }
.nxcmp-arm-note b {
  display: block; font-family: var(--font-mono); font-size: 11px; font-weight: 500;
  color: var(--text-secondary); margin-bottom: 4px;
}
.nxcmp-arm-link { margin-top: var(--space-3); }

/* ── 注记：琥珀（注意/声明），不是错误 ─────────────────────── */
.nxcmp-notes {
  margin-top: var(--space-4); padding: var(--space-3) var(--space-4);
  background: var(--amber-100); border: 1px solid var(--amber-300);
  border-left: 2px solid var(--amber-700); border-radius: var(--radius-sm);
}
.nxcmp-notes .nxcmp-eyebrow { color: var(--amber-700); }
.nxcmp-notes.is-reason { background: var(--surface-cool); border-color: var(--border-default); border-left-color: var(--border-strong); }
.nxcmp-notes.is-reason .nxcmp-eyebrow { color: var(--text-muted); }
.nxcmp-notes ul { margin: 6px 0 0; padding-left: 18px; }
.nxcmp-notes li { font-size: 11px; color: var(--text-primary); line-height: 1.8; }
.nxcmp-notes li::marker { color: var(--amber-700); }
.nxcmp-notes.is-reason li::marker { color: var(--text-disabled); }

/* ── 常驻免责条：sticky 吸底，视觉上不可消失 ───────────────── */
.nxcmp-disclaimer {
  position: sticky; bottom: 0; z-index: 1;
  margin-top: var(--space-5); padding: 10px var(--space-4);
  background: var(--surface-panel); border: 1px solid var(--amber-300);
  border-left: 2px solid var(--amber-700); border-radius: var(--radius-sm);
  display: flex; align-items: center; gap: var(--space-3);
}
.nxcmp-disclaimer-mark {
  font-family: var(--font-mono); font-size: 12px; font-weight: 700;
  color: var(--amber-700); flex: none;
}
.nxcmp-disclaimer p { margin: 0; font-size: 11px; color: var(--text-secondary); line-height: 1.7; }

/* ── 响应式：窄屏规格移到上方 ─────────────────────────────── */
@media (max-width: 900px) {
  .nxcmp-body { grid-template-columns: 1fr; }
  .nxcmp-arms { grid-template-columns: 1fr; }
  .nxcmp-head { flex-direction: column; align-items: flex-start; gap: var(--space-2); }
  .nxcmp-metric-value { font-size: 24px; }
}

@media (prefers-reduced-motion: reduce) {
  .nxcmp-head::after { transition: none; }
  .nxcmp-arm { transition: none; }
  .nxcmp-arm:hover { transform: none; }
}
</style>
