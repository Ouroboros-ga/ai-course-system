<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="sl-drawer-layer"
      @mousedown.self="$emit('close')"
    >
      <section
        ref="panelRef"
        class="sl-drawer"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        tabindex="-1"
        @keydown="handleKeydown"
      >
        <header class="sl-drawer__header">
          <h2 :id="titleId">{{ title }}</h2>
          <button
            ref="closeButtonRef"
            type="button"
            class="sl-icon-button"
            aria-label="关闭面板"
            @click="$emit('close')"
          >
            <X :size="20" />
          </button>
        </header>
        <div class="sl-drawer__body">
          <slot />
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { X } from 'lucide-vue-next'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, required: true },
})

defineEmits(['close'])

const panelRef = ref(null)
const closeButtonRef = ref(null)
const titleId = 'learning-drawer-' + Math.random().toString(36).slice(2)
let returnFocusElement = null

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function handleKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeButtonRef.value?.click()
    return
  }
  if (event.key !== 'Tab' || !panelRef.value) return

  const controls = [...panelRef.value.querySelectorAll(focusableSelector)]
  if (!controls.length) {
    event.preventDefault()
    panelRef.value.focus()
    return
  }

  const first = controls[0]
  const last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

watch(
  () => props.open,
  async open => {
    if (open) {
      returnFocusElement = document.activeElement
      await nextTick()
      closeButtonRef.value?.focus()
      document.body.classList.add('sl-drawer-open')
    } else {
      document.body.classList.remove('sl-drawer-open')
      returnFocusElement?.focus?.()
      returnFocusElement = null
    }
  }
)

onBeforeUnmount(() => {
  document.body.classList.remove('sl-drawer-open')
})
</script>