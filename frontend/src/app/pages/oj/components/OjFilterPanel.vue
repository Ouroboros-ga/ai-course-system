<script setup>
import { computed } from 'vue'
import { Search } from 'lucide-vue-next'
import SfxButton from '@/app/ui/SfxButton.vue'
import OjMultiSelect from './OjMultiSelect.vue'
import { OJ_DIFFICULTY_RANGES, difficultyRangeLabel } from '../ojTheme.js'

/**
 * OJ 题库筛选面板（复刻参考截图的筛选区）。
 *
 * 结构对齐截图：所属题库 tab 行 → 筛选条件行 → 已选择 chips 行 → 结果计数 + 操作。
 *
 * 「所属题库」= **题目来源**（Codeforces / UVA / 自编…），数据来自 B1 新增的
 * `source` 列。课程不在这里 —— 课程是**数据范围**（决定查哪个库），不是筛选条件，
 * 所以它移到页面头部，与「刷新」并列。
 *
 * 全部筛选值走 v-model，页面是唯一状态源 —— 面板不自己发请求，
 * 只在用户按「搜索」或改选项时 emit，避免每个控件都回源打接口。
 */
const props = defineProps({
  /** 有题目的来源去重列表；空数组时只显示「全部」。 */
  sources: { type: Array, default: () => [] },
  /** 有题目的年份去重列表（降序）。 */
  years: { type: Array, default: () => [] },
  tagOptions: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
  /**
   * 后端是否支持「搜索题面」（B1 的 `search_in`）。
   * 已落地 → 传 true 即可用；留这个开关是为了接口未部署时能优雅降级
   * （禁用 + 说明），而不是让勾选静默无效。
   */
  statementSearchSupported: { type: Boolean, default: false },
})

const emit = defineEmits(['search', 'clear-all'])

const activeSource = defineModel('activeSource', { type: String, default: '' })
const difficulty = defineModel('difficulty', { type: String, default: '' })
const year = defineModel('year', { type: String, default: '' })
const status = defineModel('status', { type: String, default: '' })
const search = defineModel('search', { type: String, default: '' })
const searchInStatement = defineModel('searchInStatement', { type: Boolean, default: false })
const selectedTags = defineModel('selectedTags', { type: Array, default: () => [] })
const tagMode = defineModel('tagMode', { type: String, default: 'or' })

const statusOptions = [
  { value: 'not_attempted', label: '未尝试' },
  { value: 'attempted', label: '尝试过' },
  { value: 'solved', label: '已通过' },
]

/** 已选择 chips：每个都自带删除动作，点 × 即从筛选条件里摘掉。 */
const chips = computed(() => {
  const list = []
  if (activeSource.value) {
    list.push({
      key: `source:${activeSource.value}`,
      text: `题库：${activeSource.value}`,
      remove: () => { activeSource.value = '' },
    })
  }
  if (difficulty.value) {
    list.push({
      key: `difficulty:${difficulty.value}`,
      text: `难度：${difficultyRangeLabel(difficulty.value)}`,
      remove: () => { difficulty.value = '' },
    })
  }
  for (const tag of selectedTags.value) {
    list.push({
      key: `tag:${tag}`,
      text: `标签：${tag}`,
      remove: () => { selectedTags.value = selectedTags.value.filter((item) => item !== tag) },
    })
  }
  if (tagMode.value === 'and' && selectedTags.value.length > 1) {
    list.push({ key: 'tag-mode', text: '标签：全部命中', remove: () => { tagMode.value = 'or' } })
  }
  if (year.value) {
    list.push({ key: `year:${year.value}`, text: `年份：${year.value}`, remove: () => { year.value = '' } })
  }
  if (status.value) {
    const hit = statusOptions.find((item) => item.value === status.value)
    list.push({
      key: `status:${status.value}`,
      text: `状态：${hit ? hit.label : status.value}`,
      remove: () => { status.value = '' },
    })
  }
  if (search.value.trim()) {
    list.push({ key: 'search', text: `关键词：${search.value.trim()}`, remove: () => { search.value = '' } })
  }
  return list
})

function submit() {
  emit('search')
}
</script>

<template>
  <section class="oj-filters" aria-label="题目筛选">
    <!-- 所属题库 = 题目来源（B1 的 source 列）。只有一门课时也照常显示这一行：
         它是筛选面板的视觉锚点，藏掉会让整块看起来"少了一层"。 -->
    <div class="oj-filters-row">
      <span class="oj-filters-label">所属题库</span>
      <div class="oj-bank-tabs" role="tablist" aria-label="所属题库">
        <span
          role="tab"
          tabindex="0"
          class="oj-bank-tab"
          :class="{ 'is-active': !activeSource }"
          :aria-selected="!activeSource ? 'true' : 'false'"
          @click="activeSource = ''"
          @keyup.enter="activeSource = ''"
        >全部</span>
        <span
          v-for="item in sources"
          :key="item"
          role="tab"
          tabindex="0"
          class="oj-bank-tab"
          :class="{ 'is-active': activeSource === item }"
          :aria-selected="activeSource === item ? 'true' : 'false'"
          @click="activeSource = activeSource === item ? '' : item"
          @keyup.enter="activeSource = activeSource === item ? '' : item"
        >{{ item }}</span>
        <span v-if="!sources.length" class="oj-bank-hint">
          还没有题目填写来源；教师可在「题目管理」里行内填写
        </span>
      </div>
    </div>

    <!-- 筛选条件 -->
    <div class="oj-filters-row">
      <span class="oj-filters-label">筛选条件</span>
      <select v-model="difficulty" class="sfx-select oj-ctl" aria-label="题目难度范围">
        <option v-for="range in OJ_DIFFICULTY_RANGES" :key="range.value" :value="range.value">
          {{ range.label }}
        </option>
      </select>

      <OjMultiSelect
        v-model="selectedTags"
        :options="tagOptions"
        placeholder="算法标签"
        empty-text="当前课程还没有可筛选的标签"
      />

      <!-- 标签匹配模式：只在选了 2 个以上标签时才有意义（单选时 and 与 or 等价） -->
      <select
        v-if="selectedTags.length > 1"
        v-model="tagMode"
        class="sfx-select oj-ctl oj-ctl--narrow"
        aria-label="标签匹配模式"
      >
        <option value="or">任一命中</option>
        <option value="and">全部命中</option>
      </select>

      <select v-if="years.length" v-model="year" class="sfx-select oj-ctl oj-ctl--narrow" aria-label="年份">
        <option value="">全部年份</option>
        <option v-for="item in years" :key="item" :value="String(item)">{{ item }} 年</option>
      </select>

      <select v-model="status" class="sfx-select oj-ctl" aria-label="作答状态">
        <option value="">全部状态</option>
        <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>

      <label class="oj-search">
        <input
          v-model="search"
          class="oj-search-input"
          type="search"
          placeholder="关键词"
          aria-label="关键词"
          @keyup.enter="submit"
        />
        <span
          role="button"
          tabindex="0"
          class="oj-search-go"
          aria-label="搜索"
          @click="submit"
          @keyup.enter="submit"
        ><Search :size="15" /></span>
      </label>

      <label
        class="oj-check"
        :class="{ 'is-disabled': !statementSearchSupported }"
        :title="statementSearchSupported ? '同时匹配题面正文（输入/输出格式里出现的关键词也算命中）' : '后端暂不支持按题面正文检索'"
      >
        <input v-model="searchInStatement" type="checkbox" :disabled="!statementSearchSupported" />
        <span>搜索题面</span>
      </label>
    </div>

    <!-- 已选择 -->
    <div class="oj-filters-row oj-filters-row--selected">
      <span class="oj-filters-label">已选择</span>
      <p v-if="!chips.length" class="oj-selected-empty">
        暂无，可在上方进行多维度筛选，例如：难度、算法标签、年份、作答状态。
      </p>
      <span v-for="chip in chips" :key="chip.key" class="oj-chip">
        {{ chip.text }}
        <span
          role="button"
          tabindex="0"
          class="oj-chip-x"
          :aria-label="`移除筛选 ${chip.text}`"
          @click="chip.remove()"
          @keyup.enter="chip.remove()"
        >×</span>
      </span>
    </div>

    <!-- 结果计数 + 操作 -->
    <div class="oj-filters-foot">
      <span class="oj-count">共计 <strong>{{ total }}</strong> 条结果</span>
      <div class="oj-filters-actions">
        <SfxButton variant="secondary" size="sm" :disabled="loading" @click="emit('clear-all')">清除筛选</SfxButton>
        <SfxButton variant="primary" size="sm" :loading="loading" @click="submit">
          <template #icon><Search :size="14" /></template>
          搜索
        </SfxButton>
      </div>
    </div>
  </section>
</template>

<style scoped>
.oj-filters {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-5) var(--space-6);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-5);
}

.oj-filters-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-3);
}

/* 左侧标签列固定宽度 —— 三行的标签必须纵向对齐，否则整块看起来是散的 */
.oj-filters-label {
  flex: 0 0 68px;
  font-size: var(--ui-sm-size);
  font-weight: var(--ui-md-weight);
  color: var(--text-secondary);
  white-space: nowrap;
}

.oj-filters-row--selected { align-items: flex-start; }
.oj-filters-row--selected .oj-filters-label { line-height: 22px; }

/* 所属题库 tab 行 */
.oj-bank-tabs { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-1); }
.oj-bank-tab {
  padding: var(--space-1) var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}
.oj-bank-tab:hover { color: var(--ink-900); background: var(--surface-cool); }
.oj-bank-tab.is-active { background: var(--ink-900); border-color: var(--ink-900); color: var(--text-inverse); }
.oj-bank-hint { font-size: var(--ui-sm-size); color: var(--text-muted); }

/* 基础 .sfx-select 是 width:100%（base.css）—— 横向行里必须显式约束宽度 */
.oj-ctl { width: auto; flex: 0 0 auto; min-width: 168px; }
.oj-ctl--narrow { min-width: 124px; }

.oj-search {
  display: inline-flex;
  align-items: center;
  flex: 1 1 220px;
  min-width: 200px;
  max-width: 420px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-panel);
  overflow: hidden;
  transition: border-color var(--duration-fast) var(--ease-out);
}
.oj-search:hover { border-color: var(--border-strong); }
.oj-search:focus-within { border-color: var(--color-focus); box-shadow: 0 0 0 2px var(--ink-100); }
.oj-search-input {
  flex: 1;
  min-width: 0;
  min-height: var(--control-height);
  padding: 0 var(--space-3);
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--ui-md-size);
  font-family: inherit;
}
.oj-search-go {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  align-self: stretch;
  color: var(--text-secondary);
  cursor: pointer;
  border-left: 1px solid var(--border-subtle);
}
.oj-search-go:hover { color: var(--ink-900); background: var(--surface-cool); }

.oj-check {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--ui-sm-size);
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}
.oj-check.is-disabled { cursor: not-allowed; color: var(--text-disabled); }

.oj-selected-empty { margin: 0; font-size: var(--ui-sm-size); color: var(--text-muted); line-height: 22px; }

.oj-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 1px var(--space-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-cool);
  font-size: var(--ui-sm-size);
  color: var(--text-primary);
}
.oj-chip-x {
  display: inline-flex;
  align-items: center;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}
.oj-chip-x:hover { color: var(--red-700); }

.oj-filters-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-subtle);
}
.oj-count { font-size: var(--ui-sm-size); color: var(--text-secondary); }
.oj-count strong { color: var(--text-primary); font-size: var(--ui-md-size); }
.oj-filters-actions { display: flex; align-items: center; gap: var(--space-2); }

@media (max-width: 760px) {
  .oj-filters { padding: var(--space-4); }
  .oj-filters-label { flex-basis: 100%; }
  .oj-ctl, .oj-search { width: 100%; max-width: none; flex: 1 1 100%; }
}
</style>
