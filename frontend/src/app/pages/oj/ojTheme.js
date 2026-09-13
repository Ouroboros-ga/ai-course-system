/**
 * OJ 域视觉与格式化**单点**（2026-09-13 复刻参考截图时引入）。
 *
 * 为什么单独成文件：难度色板 / 标签色板 / 题号派生 / 单位换算 / 排序口径
 * 一旦散落在列表页与详情页两处，后续调色或改题号口径必然漏改一处。
 * 集中在这里，页面只消费不定义。
 *
 * 纯函数、零副作用、不 import 任何组件 —— 可直接 `node --test` 闭环验证。
 * 设计依据见 docs/phase1/2026-09-13_OJ题目列表与详情页界面复刻_接口规范与前端改动.md
 */

/* ── 难度：三档 → 洛谷色板 ──────────────────────────────────────────
 * 后端 difficulty 枚举保持三档不动（PR-09 已用测试钉住「本域拒收 1–5」）；
 * 这里只做**展示映射**：色值取自参考截图，label 用洛谷区间名，
 * tier 保留本系统语义（简单/中等/困难）供 title 提示，避免区间名被误读为精确难度。
 */
export const OJ_DIFFICULTY_META = {
  easy: { label: '普及', color: '#F39C11', tier: '简单', order: 1 },
  medium: { label: '提高', color: '#3498DB', tier: '中等', order: 2 },
  hard: { label: '省选/NOI-', color: '#9D3DCF', tier: '困难', order: 3 },
}

/** 未标注难度的兜底（灰）。后端允许 difficulty 为空。 */
const UNSET_DIFFICULTY = { label: '暂无评定', color: '#8A94A6', tier: '未标注', order: 0 }

/** 难度升序（筛选下拉与排序都用它，别再各自写一遍数组）。 */
export const OJ_DIFFICULTY_ORDER = ['easy', 'medium', 'hard']

export function difficultyMeta(value) {
  const key = String(value ?? '').trim().toLowerCase()
  return OJ_DIFFICULTY_META[key] || UNSET_DIFFICULTY
}

export function difficultyLabel(value) {
  return difficultyMeta(value).label
}

/* ── 标签着色 ──────────────────────────────────────────────────────
 * 参考截图的算法标签是多色的：来源类走蓝，年份单独走橙。
 * 本系统 tags 是自由字符串、无来源/年份结构（见接口规范 B1），
 * 因此用**确定性哈希**取色 —— 同一个标签在任何页面、任何会话都是同一个颜色，
 * 不会每次渲染乱跳。结构化 source/year 落地后，这里替换为按维度取色即可。
 */
const TAG_PALETTE = ['#3498DB', '#0FA3A3', '#52C41A', '#9D3DCF', '#E2574C', '#2D7DD2']
const TAG_YEAR_COLOR = '#E67E22'
const YEAR_PATTERN = /^(19|20)\d{2}$/

export function tagColor(tag) {
  const text = String(tag ?? '').trim()
  if (!text) return TAG_PALETTE[0]
  if (YEAR_PATTERN.test(text)) return TAG_YEAR_COLOR
  let hash = 0
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) >>> 0
  }
  return TAG_PALETTE[hash % TAG_PALETTE.length]
}

/* ── 题号派生（课程内序号口径）────────────────────────────────────
 * 服务端（`domain/oj/problems/catalog.py`）已下发 `problem_no`，**以服务端为准**；
 * 这里保留派生实现作为降级路径（接口未部署 / 离线演示时仍能显示连续题号）。
 * ⚠️ 顺序源必须是**未筛选的全量课程目录**：拿筛选后的结果编号，
 * 一筛选题号就整套平移，学生会以为自己看错了题。
 * ⚠️ 必须用 **code-point 比较**，不能用 `localeCompare` —— 服务端用 Python
 * `sorted()`（code-point），而 locale 比对会把 `-` 之类的标点当作可忽略字符，
 * 两端排出不同顺序时同一道题在两处的题号就不一致了。
 */
export function formatProblemNo(seq) {
  const n = Number(seq)
  if (!Number.isFinite(n) || n <= 0) return '—'
  return `#${String(Math.trunc(n)).padStart(3, '0')}`
}

/** code-point 升序比较器。与服务端 `sorted()` 的默认顺序一致。 */
export function compareCodepoints(a, b) {
  if (a === b) return 0
  return a < b ? -1 : 1
}

export function buildProblemNoIndex(problems, key = 'experiment_id') {
  const ids = (Array.isArray(problems) ? problems : [])
    .map((item) => String(item?.[key] ?? ''))
    .filter(Boolean)
  const index = new Map()
  ;[...new Set(ids)].sort(compareCodepoints).forEach((id, i) => {
    index.set(id, formatProblemNo(i + 1))
  })
  return index
}

/**
 * 题号取值：服务端字段优先，缺失时降级到本地派生索引。
 * `sort_index` 是服务端给的 1-based 序号，与 `problem_no` 同源。
 */
export function resolveProblemNo(problem, fallbackIndex) {
  const provided = problem?.problem_no
  if (typeof provided === 'string' && provided && provided !== '—') return provided
  return fallbackIndex?.get(String(problem?.experiment_id ?? '')) || '—'
}

/* ── 单位与数值格式化 ──────────────────────────────────────────────
 * 参考截图写 `时间限制: 1.00s` / `内存限制: 62.50MB`。
 * ⚠️ Judge0 的 memory_limit 单位是 **KB**，直接显示会得到「128000」。
 */
const KIB = 1024

export function formatMemoryLimit(kb) {
  const n = Number(kb)
  if (!Number.isFinite(n) || n <= 0) return null
  return `${(n / KIB).toFixed(2)}MB`
}

export function formatTimeLimit(seconds) {
  const n = Number(seconds)
  if (!Number.isFinite(n) || n <= 0) return null
  return `${n.toFixed(2)}s`
}

export function formatPassRate(rate) {
  const n = Number(rate)
  if (rate === null || rate === undefined || !Number.isFinite(n)) return null
  return `${(n * 100).toFixed(1)}%`
}

/** 通过率进度条宽度百分比（保留最小可见宽度，避免「0%」时条完全消失）。 */
export function passRateWidth(rate) {
  const n = Number(rate)
  if (!Number.isFinite(n) || n <= 0) return '0%'
  return `${Math.min(100, Math.max(2, n * 100)).toFixed(1)}%`
}

/* ── 排序 ──────────────────────────────────────────────────────────
 * ⚠️ 现行后端是「先分页再返回」，所以前端排序只覆盖当前页。
 * 接口规范 B1 已提出把排序下沉到服务端；在它落地前，这里排的是**当前页**，
 * 页面必须在 UI 上说明这点，别让学生以为看到了全库第 1 名。
 */
const SORT_ACCESSORS = {
  no: (p, noOf) => ({ v: String(noOf?.(p) ?? ''), missing: false }),
  title: (p) => ({ v: String(p?.title ?? ''), missing: false }),
  difficulty: (p) => ({ v: difficultyMeta(p?.difficulty).order, missing: false }),
  pass_rate: (p) => ({
    v: p?.pass_rate,
    missing: p?.pass_rate === null || p?.pass_rate === undefined,
  }),
  attempt_total: (p) => ({
    v: p?.attempt_total,
    missing: p?.attempt_total === null || p?.attempt_total === undefined,
  }),
}

export const OJ_SORTABLE_KEYS = Object.keys(SORT_ACCESSORS)

export function sortProblems(items, { sortBy = 'default', sortOrder = 'asc', problemNoOf } = {}) {
  const list = Array.isArray(items) ? [...items] : []
  const accessor = SORT_ACCESSORS[sortBy]
  if (!accessor) return list
  const dir = sortOrder === 'desc' ? -1 : 1
  return list.sort((a, b) => {
    const left = accessor(a, problemNoOf)
    const right = accessor(b, problemNoOf)
    // 「无数据」永远沉底，不随升降序翻转 —— 否则降序时一排「—」顶在最前面，
    // 看起来像最差的一批，实际只是没人交过。
    if (left.missing && right.missing) return 0
    if (left.missing) return 1
    if (right.missing) return -1
    if (typeof left.v === 'number' && typeof right.v === 'number') {
      return dir * (left.v - right.v)
    }
    return dir * String(left.v).localeCompare(String(right.v), 'zh')
  })
}
