<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  Check, ChevronLeft, ChevronRight, CircleAlert, Clock, LoaderCircle, Minus,
} from 'lucide-vue-next'

/**
 * 通用 Local Rail（page-design §3.2/§3.4/§6.4，design.md 4.6）。
 *
 * - 三级工作区切换：点击更新 URL，保留二级导航，不打开右侧抽屉。
 * - 管理/建设/治理页默认展开；沉浸任务页默认收缩（§3.4）。
 * - 用户手动选择后按 storageKey 记住该设备上的展开状态。
 * - 每项可带：图标、名称、状态（done/current/pending/failed/todo）、待处理数量。
 * - 禁用项按 §1.5 给出原因，不渲染空壳菜单。
 */
const props = defineProps({
  items: { type: Array, required: true },
  // [{ key, label, to, icon?, status?, count?, disabled?, reason? }]
  ariaLabel: { type: String, default: '工作区导航' },
  storageKey: { type: String, default: '' },
  defaultCollapsed: { type: Boolean, default: false },
})

const route = useRoute()

const collapsed = ref(props.defaultCollapsed)

if (props.storageKey) {
  try {
    const saved = localStorage.getItem(`sfx:rail:${props.storageKey}`)
    if (saved === '1' || saved === '0') collapsed.value = saved === '1'
  } catch { /* localStorage 不可用时保持默认 */ }
}

watch(collapsed, (value) => {
  if (!props.storageKey) return
  try { localStorage.setItem(`sfx:rail:${props.storageKey}`, value ? '1' : '0') } catch { /* ignore */ }
})

const statusMeta = {
  done: { icon: Check, cls: 'is-done', label: '已完成' },
  current: { icon: ChevronRight, cls: 'is-current', label: '当前' },
  pending: { icon: Clock, cls: 'is-pending', label: '待处理' },
  failed: { icon: CircleAlert, cls: 'is-failed', label: '存在失败' },
  running: { icon: LoaderCircle, cls: 'is-running', label: '进行中' },
  todo: { icon: Minus, cls: 'is-todo', label: '未开始' },
}

function itemStatus(item) {
  return item.status ? statusMeta[item.status] ?? null : null
}

function isActive(item) {
  if (item.active === true) return true
  if (!item.to) return false
  return route.path === item.to || route.path.startsWith(`${item.to}/`)
}

const railCls = computed(() => (collapsed.value ? 'is-collapsed' : 'is-expanded'))
</script>

<template>
  <aside class="sfx-rail" :class="railCls" :aria-label="ariaLabel">
    <nav class="sfx-rail-nav">
      <template v-for="item in items" :key="item.key">
        <span
          v-if="item.disabled"
          class="sfx-rail-item is-disabled"
          :title="item.reason || '暂不可用'"
          aria-disabled="true"
        >
          <component :is="item.icon" v-if="item.icon" :size="17" class="sfx-rail-item-icon" />
          <span class="sfx-rail-item-label">{{ item.label }}</span>
        </span>
        <RouterLink
          v-else
          :to="item.to"
          class="sfx-rail-item"
          :class="{ 'is-active': isActive(item) }"
          :title="collapsed ? item.label : ''"
        >
          <component :is="item.icon" v-if="item.icon" :size="17" class="sfx-rail-item-icon" />
          <span class="sfx-rail-item-label">{{ item.label }}</span>
          <span v-if="item.count" class="sfx-rail-item-count" :aria-label="`${item.count} 项待处理`">
            {{ item.count > 99 ? '99+' : item.count }}
          </span>
          <span
            v-if="itemStatus(item)"
            class="sfx-rail-item-status"
            :class="itemStatus(item).cls"
            :title="itemStatus(item).label"
            :aria-label="itemStatus(item).label"
          >
            <component :is="itemStatus(item).icon" :size="13" :stroke-width="2.4" />
          </span>
        </RouterLink>
      </template>
    </nav>

    <button
      type="button"
      class="sfx-rail-toggle"
      :aria-expanded="!collapsed"
      :aria-label="collapsed ? '展开导航栏' : '收缩导航栏'"
      :title="collapsed ? '展开' : '收缩'"
      @click="collapsed = !collapsed"
    >
      <ChevronLeft v-if="!collapsed" :size="16" />
      <ChevronRight v-else :size="16" />
    </button>
    <!-- 可选底部区域：放置"返回上级工作区"等跨布局入口 -->
    <div v-if="$slots.footer" class="sfx-rail-footer">
      <slot name="footer" />
    </div>
  </aside>
</template>

<style scoped>
.sfx-rail {
  position: relative;
  flex-shrink: 0;
  background: var(--surface-soft);
  border-right: 1px solid var(--border-default);
  display: flex;
  flex-direction: column;
  transition: width var(--duration-normal) var(--ease-out);
}

.sfx-rail.is-expanded { width: var(--rail-width); }
.sfx-rail.is-collapsed { width: var(--rail-width-collapsed); }

.sfx-rail-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-3) var(--space-2);
  overflow-y: auto;
}

.sfx-rail-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 40px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: var(--ui-md-size);
  font-weight: var(--ui-md-weight);
  white-space: nowrap;
}

.sfx-rail-item:hover:not(.is-disabled):not(.is-active) {
  background: var(--border-subtle);
  color: var(--ink-700);
}

/* 当前项：浅墨蓝背景 + 左侧 3px 状态线（design.md 4.6） */
.sfx-rail-item.is-active {
  background: var(--ink-100);
  color: var(--ink-900);
}

.sfx-rail-item.is-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: var(--radius-full);
  background: var(--ink-900);
}

.sfx-rail-item.is-disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

.sfx-rail-item-icon { flex-shrink: 0; }

.sfx-rail-item-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sfx-rail-item-count {
  flex-shrink: 0;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: var(--radius-full);
  background: var(--amber-100);
  color: var(--amber-700);
  font-size: var(--caption-size);
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.sfx-rail-item-status { flex-shrink: 0; display: inline-flex; }
.sfx-rail-item-status.is-done { color: var(--green-500); }
.sfx-rail-item-status.is-current { color: var(--ink-500); }
.sfx-rail-item-status.is-pending { color: var(--amber-500); }
.sfx-rail-item-status.is-failed { color: var(--red-500); }
.sfx-rail-item-status.is-running { color: var(--ink-500); }
.sfx-rail-item-status.is-todo { color: var(--text-disabled); }

.sfx-rail-toggle {
  position: absolute;
  top: var(--space-3);
  right: -13px;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-full);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 5;
}

.sfx-rail-toggle:hover { color: var(--ink-700); border-color: var(--border-strong); }

/* 底部区域：与导航列表用分隔线隔开（收缩态隐藏文字类入口由调用方控制） */
.sfx-rail-footer {
  flex-shrink: 0;
  padding: var(--space-2);
  border-top: 1px solid var(--border-default);
}
.sfx-rail-footer :deep(a) {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 34px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: var(--ui-sm-size);
  font-weight: var(--ui-md-weight);
  white-space: nowrap;
  text-decoration: none;
}
.sfx-rail-footer :deep(a):hover { background: var(--ink-100); color: var(--ink-900); }

/* 收缩态：只显示图标与状态点，Hover 由 title 展示名称（design.md 4.6） */
.sfx-rail.is-collapsed .sfx-rail-item { justify-content: center; padding: 0; }
.sfx-rail.is-collapsed .sfx-rail-item-label { display: none; }
/* 收缩态空间不足，底部文字入口隐藏（可用 L2 导航替代返回） */
.sfx-rail.is-collapsed .sfx-rail-footer { display: none; }
.sfx-rail.is-collapsed .sfx-rail-item-count {
  position: absolute;
  top: 2px;
  right: 2px;
  min-width: 14px;
  height: 14px;
  font-size: 9px;
  padding: 0 3px;
}
.sfx-rail.is-collapsed .sfx-rail-item-status {
  position: absolute;
  bottom: 2px;
  right: 2px;
}

/* 移动端（design.md §12.5）：rail 变横向滚动条，不收起，隐藏收起按钮 */
@media (max-width: 760px) {
  .sfx-rail {
    width: 100% !important;
    flex-direction: column;
    border-right: none;
    border-bottom: 1px solid var(--border-default);
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
  }

  .sfx-rail-nav {
    flex: none;
    flex-direction: row;
    align-items: center;
    gap: var(--space-1);
    padding: var(--space-2);
    overflow: visible;
    min-width: max-content;
  }

  .sfx-rail-item {
    min-height: 36px;
    padding: 0 var(--space-2);
  }

  /* 当前项状态线改到顶部（横向条场景） */
  .sfx-rail-item.is-active::before {
    left: 8px;
    right: 8px;
    top: 0;
    bottom: auto;
    width: auto;
    height: 3px;
  }

  .sfx-rail-toggle { display: none; }
  /* 横向条场景底部入口无独立空间，隐藏（移动端用 L2 导航返回） */
  .sfx-rail-footer { display: none; }

  /* 收缩态在移动端始终展示完整标签 */
  .sfx-rail.is-collapsed .sfx-rail-item { justify-content: flex-start; padding: 0 var(--space-2); }
  .sfx-rail.is-collapsed .sfx-rail-item-label { display: block; }
  .sfx-rail.is-collapsed .sfx-rail-item-count,
  .sfx-rail.is-collapsed .sfx-rail-item-status { position: static; }
}
</style>
