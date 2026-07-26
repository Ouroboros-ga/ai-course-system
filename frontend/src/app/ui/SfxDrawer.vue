<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { X } from 'lucide-vue-next'

/**
 * 右侧聚焦抽屉（page-design §4.9/§5.5，design.md 4.9）。
 *
 * - 宽度 420 / 480 / 640px，右侧滑入，遮罩 surface-overlay；
 * - 标题说明当前动作；底部固定主操作与取消（footer slot）；
 * - Esc 或遮罩关闭；关闭后焦点返回触发元素；
 * - 禁止在抽屉中再打开第二个抽屉（§6.6）。
 */
const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, required: true },
  width: { type: Number, default: 480, validator: (v) => [420, 480, 640].includes(v) },
})

const emit = defineEmits(['close'])

const panelRef = ref(null)
let previousActiveElement = null

function requestClose() {
  emit('close')
}

function handleEsc(e) {
  if (e.key === 'Escape' && props.open) requestClose()
}

watch(
  () => props.open,
  async (value) => {
    if (value) {
      previousActiveElement = document.activeElement
      document.addEventListener('keydown', handleEsc)
      document.body.style.overflow = 'hidden'
      await nextTick()
      panelRef.value?.focus()
    } else {
      document.removeEventListener('keydown', handleEsc)
      document.body.style.overflow = ''
      // §4.9：关闭后焦点返回触发按钮
      if (previousActiveElement && typeof previousActiveElement.focus === 'function') {
        previousActiveElement.focus()
      }
      previousActiveElement = null
    }
  },
)

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleEsc)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="sfx-drawer-overlay" @click.self="requestClose">
      <section
        ref="panelRef"
        class="sfx-drawer sfx"
        :style="{ width: `${width}px` }"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        tabindex="-1"
      >
        <header class="sfx-drawer-header">
          <h2 class="sfx-drawer-title sfx-t-title3">{{ title }}</h2>
          <button
            type="button"
            class="sfx-drawer-close"
            aria-label="关闭抽屉"
            @click="requestClose"
          >
            <X :size="18" />
          </button>
        </header>

        <div class="sfx-drawer-body">
          <slot />
        </div>

        <footer v-if="$slots.footer" class="sfx-drawer-footer">
          <slot name="footer" />
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.sfx-drawer-overlay {
  position: fixed;
  inset: 0;
  background: var(--surface-overlay);
  z-index: 90;
  display: flex;
  justify-content: flex-end;
  animation: sfx-drawer-fade var(--duration-fast) var(--ease-out);
}

.sfx-drawer {
  height: 100%;
  max-width: 100vw;
  background: var(--surface-panel);
  border-left: 1px solid var(--border-strong);
  border-radius: var(--radius-xl) 0 0 var(--radius-xl);
  box-shadow: var(--shadow-md);
  display: flex;
  flex-direction: column;
  animation: sfx-drawer-slide var(--duration-normal) var(--ease-out);
  outline: none;
}

.sfx-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-5, 20px) var(--space-6);
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.sfx-drawer-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
}

.sfx-drawer-close:hover { background: var(--surface-cool); color: var(--ink-700); }

.sfx-drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.sfx-drawer-footer {
  flex-shrink: 0;
  padding: var(--space-4) var(--space-6);
  border-top: 1px solid var(--border-subtle);
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
}

@keyframes sfx-drawer-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes sfx-drawer-slide {
  from { transform: translateX(48px); opacity: 0.6; }
  to { transform: translateX(0); opacity: 1; }
}
</style>
