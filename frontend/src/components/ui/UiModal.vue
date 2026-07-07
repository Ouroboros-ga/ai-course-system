<script setup>
import { watch, onBeforeUnmount } from 'vue'
import { X } from 'lucide-vue-next'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  title: {
    type: String,
    default: '',
  },
  width: {
    type: String,
    default: '500px',
  },
})

const emit = defineEmits(['update:modelValue'])

function close() {
  emit('update:modelValue', false)
}

function handleMaskClick(e) {
  if (e.target === e.currentTarget) {
    close()
  }
}

function handleKeydown(e) {
  if (e.key === 'Escape') {
    close()
  }
}

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      document.addEventListener('keydown', handleKeydown)
      document.body.style.overflow = 'hidden'
    } else {
      document.removeEventListener('keydown', handleKeydown)
      document.body.style.overflow = ''
    }
  },
)

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <Transition name="ui-modal">
      <div v-if="modelValue" class="ui-modal__mask" @click="handleMaskClick">
        <div
          class="ui-modal__dialog"
          role="dialog"
          aria-modal="true"
          :style="{ maxWidth: width }"
        >
          <div class="ui-modal__header">
            <h3 class="ui-modal__title">{{ title }}</h3>
            <button class="ui-modal__close" type="button" aria-label="关闭" @click="close">
              <X :size="20" />
            </button>
          </div>
          <div class="ui-modal__body">
            <slot />
          </div>
          <div v-if="$slots.footer" class="ui-modal__footer">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ui-modal__mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  z-index: var(--z-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-sans);
}

.ui-modal__dialog {
  position: relative;
  z-index: var(--z-modal);
  width: 90%;
  max-height: 85vh;
  overflow-y: auto;
  background: var(--color-surface);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-xl);
}

.ui-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.ui-modal__title {
  margin: 0;
  font-size: var(--text-xl);
  font-weight: var(--font-bold);
  color: var(--color-text);
  line-height: var(--leading-tight);
}

.ui-modal__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: transparent;
  border: none;
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition:
    background var(--duration-normal) var(--ease),
    color var(--duration-normal) var(--ease);
}

.ui-modal__close:hover {
  background: var(--color-surface-2);
  color: var(--color-text);
}

.ui-modal__close:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.ui-modal__body {
  padding: var(--space-5);
  color: var(--color-text);
}

.ui-modal__footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--color-border);
}

/* ── 过渡动画：fade + scale ── */
.ui-modal-enter-active,
.ui-modal-leave-active {
  transition:
    opacity var(--duration-slow) var(--ease);
}

.ui-modal-enter-active .ui-modal__dialog,
.ui-modal-leave-active .ui-modal__dialog {
  transition:
    transform var(--duration-slow) var(--ease-spring),
    opacity var(--duration-slow) var(--ease);
}

.ui-modal-enter-from,
.ui-modal-leave-to {
  opacity: 0;
}

.ui-modal-enter-from .ui-modal__dialog,
.ui-modal-leave-to .ui-modal__dialog {
  transform: scale(0.92);
  opacity: 0;
}
</style>
