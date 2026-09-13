<script setup>
import { computed } from 'vue'
import { ChevronDown, ChevronUp } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'
import SfxEmpty from '@/app/ui/SfxEmpty.vue'
import {
  difficultyMeta,
  formatPassRate,
  passRateWidth,
  tagColor,
} from '../ojTheme.js'

/**
 * OJ 题表（复刻参考截图的表格区）。
 * 列序与截图一致：题号 / 题目名称 / 显示算法标签 / 难度 / 通过率，
 * 末尾追加「我的状态」—— 截图没有，但课程内 OJ 缺了它就是功能倒退（见接口规范 3.3）。
 *
 * ⚠️ 排序目前只作用于**当前页**（后端先分页再返回，见接口规范 B1 的 P1 注解）。
 * 表头 tooltip 明确写出这一点，不让用户以为看到的是全库第 1 名。
 */
const props = defineProps({
  problems: { type: Array, default: () => [] },
  problemNoOf: { type: Function, default: null },
  loading: { type: Boolean, default: false },
  /** 排序下沉到服务端后置 true，用于把「仅当前页」的提示换成「全库」。 */
  serverSort: { type: Boolean, default: false },
})

const emit = defineEmits(['open'])

const sortBy = defineModel('sortBy', { type: String, default: 'default' })
const sortOrder = defineModel('sortOrder', { type: String, default: 'asc' })
const selected = defineModel('selected', { type: Array, default: () => [] })
const multiSelect = defineModel('multiSelect', { type: Boolean, default: false })

const sortHint = computed(() => (props.serverSort ? '全库排序' : '排序仅作用于当前页'))

function problemNo(problem) {
  return props.problemNoOf ? props.problemNoOf(problem) : '—'
}

function toggleSort(key) {
  if (sortBy.value === key) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortBy.value = key
    sortOrder.value = 'asc'
  }
}

function sortIcon(key) {
  if (sortBy.value !== key) return null
  return sortOrder.value === 'asc' ? ChevronUp : ChevronDown
}

function isSelected(problem) {
  return selected.value.includes(problem.experiment_id)
}

function toggleRow(problem) {
  const id = problem.experiment_id
  selected.value = isSelected(problem)
    ? selected.value.filter((item) => item !== id)
    : [...selected.value, id]
}

const allSelected = computed(() => (
  props.problems.length > 0 && props.problems.every((item) => isSelected(item))
))

function toggleAll() {
  selected.value = allSelected.value ? [] : props.problems.map((item) => item.experiment_id)
}

function statusMeta(value) {
  return {
    solved: { label: '已通过', cls: 'is-solved' },
    attempted: { label: '尝试过', cls: 'is-attempted' },
    not_attempted: { label: '未尝试', cls: 'is-idle' },
  }[value] || { label: value || '—', cls: 'is-idle' }
}

function openProblem(problem) {
  emit('open', problem)
}

function practiceSelected() {
  const first = props.problems.find((item) => isSelected(item))
  if (first) emit('open', first)
}
</script>

<template>
  <section class="oj-table-panel" aria-label="题目列表">
    <SfxEmpty
      v-if="!loading && !problems.length"
      title="没有符合条件的题目"
      description="调整筛选条件，或等教师发布新题目。"
    />

    <div v-else class="oj-table-scroll">
      <table class="oj-table">
        <thead>
          <tr>
            <th class="oj-col-check">
              <span
                role="checkbox"
                tabindex="0"
                class="oj-box"
                :class="{ 'is-on': allSelected }"
                :aria-checked="allSelected ? 'true' : 'false'"
                aria-label="全选本页"
                @click="toggleAll"
                @keyup.enter="toggleAll"
              ></span>
            </th>
            <th class="oj-col-no">
              <span
                role="button"
                tabindex="0"
                class="oj-th-sort"
                :class="{ 'is-active': sortBy === 'no' }"
                :title="sortHint"
                @click="toggleSort('no')"
                @keyup.enter="toggleSort('no')"
              >
                题号
                <component :is="sortIcon('no')" v-if="sortIcon('no')" :size="12" />
                <ChevronsUpDown v-else :size="12" class="oj-sort-idle" />
              </span>
            </th>
            <th>
              <span
                role="button"
                tabindex="0"
                class="oj-th-sort"
                :class="{ 'is-active': sortBy === 'title' }"
                :title="sortHint"
                @click="toggleSort('title')"
                @keyup.enter="toggleSort('title')"
              >
                题目名称
                <component :is="sortIcon('title')" v-if="sortIcon('title')" :size="12" />
              </span>
            </th>
            <th>显示算法标签</th>
            <th class="oj-col-difficulty">
              <span
                role="button"
                tabindex="0"
                class="oj-th-sort"
                :class="{ 'is-active': sortBy === 'difficulty' }"
                :title="sortHint"
                @click="toggleSort('difficulty')"
                @keyup.enter="toggleSort('difficulty')"
              >
                难度
                <component :is="sortIcon('difficulty')" v-if="sortIcon('difficulty')" :size="12" />
                <ChevronsUpDown v-else :size="12" class="oj-sort-idle" />
              </span>
            </th>
            <th class="oj-col-rate">
              <span
                role="button"
                tabindex="0"
                class="oj-th-sort"
                :class="{ 'is-active': sortBy === 'pass_rate' }"
                :title="sortHint"
                @click="toggleSort('pass_rate')"
                @keyup.enter="toggleSort('pass_rate')"
              >
                通过率
                <component :is="sortIcon('pass_rate')" v-if="sortIcon('pass_rate')" :size="12" />
              </span>
            </th>
            <th class="oj-col-status">我的状态</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in problems"
            :key="item.experiment_id"
            class="oj-row"
            :style="{ '--oj-accent': difficultyMeta(item.difficulty).color }"
            @click="openProblem(item)"
          >
            <td v-if="multiSelect" class="oj-col-check">
              <span
                role="checkbox"
                tabindex="0"
                class="oj-box"
                :class="{ 'is-on': isSelected(item) }"
                :aria-checked="isSelected(item) ? 'true' : 'false'"
                :aria-label="`选择 ${item.title}`"
                @click.stop="toggleRow(item)"
                @keyup.enter.stop="toggleRow(item)"
              ></span>
            </td>
            <td class="oj-col-no oj-mono">{{ problemNo(item) }}</td>
            <td class="oj-col-title">
              <span
                role="link"
                tabindex="0"
                class="oj-title-link"
                @click.stop="openProblem(item)"
                @keyup.enter.stop="openProblem(item)"
              >{{ item.title }}</span>
            </td>
            <td class="oj-col-tags">
              <span
                v-for="tag in (item.tags || [])"
                :key="tag"
                class="oj-algo-tag"
                :style="{ background: tagColor(tag) }"
              >{{ tag }}</span>
              <span v-if="!(item.tags || []).length" class="oj-dash">—</span>
            </td>
            <td class="oj-col-difficulty">
              <span
                class="oj-difficulty"
                :style="{ background: difficultyMeta(item.difficulty).color }"
                :title="`本系统难度：${difficultyMeta(item.difficulty).tier}`"
              >{{ difficultyMeta(item.difficulty).label }}</span>
            </td>
            <td class="oj-col-rate">
              <div class="oj-rate">
                <span class="oj-rate-track">
                  <span class="oj-rate-fill" :style="{ width: passRateWidth(item.pass_rate) }"></span>
                </span>
                <span class="oj-rate-text">{{ formatPassRate(item.pass_rate) || '—' }}</span>
              </div>
            </td>
            <td class="oj-col-status">
              <span class="oj-status" :class="statusMeta(item.my_status).cls">{{ statusMeta(item.my_status).label }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 底部：多选开关 + 已选动作（截图底部的「多选」位） -->
    <div v-if="problems.length" class="oj-table-foot">
      <label class="oj-multi-toggle">
        <input v-model="multiSelect" type="checkbox" />
        <span>多选</span>
      </label>
      <div v-if="multiSelect && selected.length" class="oj-batch">
        <span class="oj-batch-count">已选 {{ selected.length }} 题</span>
        <SfxButton variant="secondary" size="sm" @click="selected = []">清空</SfxButton>
        <SfxButton variant="primary" size="sm" @click="practiceSelected">开始练习</SfxButton>
      </div>
      <span v-else class="oj-table-foot-hint">{{ sortHint }}；勾选后可进入所选题目。</span>
    </div>
  </section>
</template>

<style scoped>
.oj-table-panel {
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.oj-table-scroll { overflow-x: auto; }

.oj-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--ui-md-size);
}
.oj-table th,
.oj-table td {
  text-align: left;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
  vertical-align: middle;
}
.oj-table thead th {
  background: var(--surface-cool);
  border-bottom: 1px solid var(--border-default);
  font-size: var(--ui-sm-size);
  font-weight: var(--ui-md-weight);
  color: var(--text-secondary);
  white-space: nowrap;
}
.oj-th-sort {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: inherit;
  cursor: pointer;
  user-select: none;
}
.oj-th-sort:hover, .oj-th-sort.is-active { color: var(--ink-900); }
/* 未激活的排序指示（参考截图表头的 ⇅）—— 弱到不抢视线，但让"这列可排序"可被发现 */
.oj-sort-idle { color: var(--text-disabled); opacity: 0.7; }
.oj-th-sort:hover .oj-sort-idle { color: var(--text-secondary); opacity: 1; }

/* 行：行首难度色竖条（截图每行左侧的彩色标记） */
.oj-row { cursor: pointer; position: relative; }
.oj-row:hover { background: var(--surface-cool); }
.oj-row td:first-child { position: relative; }
.oj-row td:first-child::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--oj-accent, transparent);
  opacity: 0.85;
}

.oj-col-check { width: 44px; }
.oj-col-no { width: 96px; white-space: nowrap; color: var(--text-secondary); font-size: var(--ui-sm-size); }
.oj-col-title { min-width: 200px; }
.oj-col-difficulty { width: 132px; }
.oj-col-rate { width: 168px; }
.oj-col-status { width: 104px; }

.oj-mono { font-family: var(--font-mono); }

.oj-box {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 15px;
  height: 15px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-xs);
  background: var(--surface-panel);
  cursor: pointer;
}
.oj-box:hover { border-color: var(--ink-700); }
.oj-box.is-on { background: var(--ink-900); border-color: var(--ink-900); }
.oj-box.is-on::after {
  content: '';
  width: 7px;
  height: 4px;
  border-left: 2px solid var(--surface-panel);
  border-bottom: 2px solid var(--surface-panel);
  transform: rotate(-45deg) translateY(-1px);
}

.oj-title-link {
  color: var(--ink-900);
  font-weight: var(--ui-md-weight);
  cursor: pointer;
  overflow-wrap: anywhere;
}
.oj-title-link:hover { color: var(--text-link); text-decoration: underline; }

/* 算法标签：多色 chip（截图里的彩色标签列） */
.oj-algo-tag {
  display: inline-block;
  margin: 1px var(--space-1) 1px 0;
  padding: 1px var(--space-2);
  border-radius: var(--radius-xs);
  font-size: 11px;
  line-height: 17px;
  color: #fff;
  white-space: nowrap;
}

/* 难度标签：洛谷色板实心 */
.oj-difficulty {
  display: inline-block;
  padding: 2px var(--space-2);
  border-radius: var(--radius-xs);
  font-size: 12px;
  line-height: 18px;
  color: #fff;
  white-space: nowrap;
}

.oj-rate { display: flex; align-items: center; gap: var(--space-2); }
.oj-rate-track {
  flex: 1;
  min-width: 56px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--ink-100);
  overflow: hidden;
}
.oj-rate-fill {
  display: block;
  height: 100%;
  border-radius: var(--radius-full);
  background: #3498DB;
}
.oj-rate-text { flex: 0 0 auto; font-size: var(--ui-sm-size); color: var(--text-secondary); min-width: 44px; }

.oj-status { font-size: var(--ui-sm-size); white-space: nowrap; }
.oj-status.is-solved { color: var(--green-700); }
.oj-status.is-attempted { color: var(--amber-700); }
.oj-status.is-idle { color: var(--text-muted); }

.oj-dash { color: var(--text-muted); }

.oj-table-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--border-default);
  background: var(--surface-canvas);
}
.oj-multi-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
}
.oj-batch { display: flex; align-items: center; gap: var(--space-2); }
.oj-batch-count { font-size: var(--ui-sm-size); color: var(--text-primary); }
.oj-table-foot-hint { font-size: var(--ui-sm-size); color: var(--text-muted); }

@media (max-width: 1024px) {
  .oj-table { min-width: 900px; }
}
</style>
