<template>
  <div class="ev-page-viewer" ref="containerRef">
    <!-- Toolbar -->
    <div class="ev-viewer-toolbar">
      <!-- Page navigation -->
      <div class="ev-toolbar-group">
        <button
          class="ev-toolbar-btn"
          :disabled="currentPage <= 1"
          title="Previous page"
          aria-label="Previous page"
          @click="$emit('prev-page')"
        >
          &#9664;
        </button>
        <span class="ev-page-indicator">
          <input
            class="ev-page-input"
            type="number"
            :value="currentPage"
            min="1"
            :max="totalPages"
            aria-label="Page number"
            @change="onPageInput"
            @keydown.enter="onPageInput"
          />
          <span class="ev-page-separator">/</span>
          <span class="ev-page-total">{{ totalPages }}</span>
        </span>
        <button
          class="ev-toolbar-btn"
          :disabled="currentPage >= totalPages"
          title="Next page"
          aria-label="Next page"
          @click="$emit('next-page')"
        >
          &#9654;
        </button>
      </div>

      <!-- Zoom controls -->
      <div class="ev-toolbar-group">
        <button
          class="ev-toolbar-btn"
          title="Zoom out"
          aria-label="Zoom out"
          @click="$emit('zoom-out')"
        >
          &#8722;
        </button>
        <span class="ev-zoom-label">{{ (zoom * 100).toFixed(0) }}%</span>
        <button
          class="ev-toolbar-btn"
          title="Zoom in"
          aria-label="Zoom in"
          @click="$emit('zoom-in')"
        >
          &#43;
        </button>
        <button
          class="ev-toolbar-btn"
          title="Reset zoom"
          aria-label="Reset zoom"
          @click="$emit('zoom-reset')"
        >
          &#8634;
        </button>
      </div>

      <!-- Rotation controls -->
      <div class="ev-toolbar-group">
        <button
          class="ev-toolbar-btn"
          title="Rotate clockwise"
          aria-label="Rotate clockwise"
          @click="$emit('rotate-cw')"
        >
          &#8635;
        </button>
        <span class="ev-rotation-label">{{ rotation }}&deg;</span>
      </div>

      <!-- Status indicator -->
      <div class="ev-toolbar-group ev-toolbar-right">
        <StatusIndicator
          v-if="status"
          :status="status"
          size="sm"
        />
      </div>
    </div>

    <!-- Page image area -->
    <div
      class="ev-page-area"
      :style="{ transform: `scale(${zoom})`, transformOrigin: 'center center' }"
    >
      <div
        class="ev-page-container"
        :style="{ width: displayWidth + 'px', height: displayHeight + 'px' }"
      >
        <!-- Page image -->
        <img
          v-if="pageImageUrl"
          :src="pageImageUrl"
          :alt="`Page ${currentPage}`"
          class="ev-page-image"
          :style="{ transform: `rotate(${rotation}deg)` }"
          @load="onImageLoad"
          ref="imageRef"
        />

        <!-- No image placeholder -->
        <div v-else class="ev-page-placeholder">
          <p>Page {{ currentPage }} image unavailable</p>
        </div>

        <!-- Highlight overlay -->
        <HighlightOverlay
          v-if="showOverlay"
          :highlights="highlights"
          :displayWidth="displayWidth"
          :displayHeight="displayHeight"
          :zoom="1.0"
          :rotation="rotation"
          :activeKey="activeCitationKey"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import HighlightOverlay from './HighlightOverlay.vue'
import StatusIndicator from './StatusIndicator.vue'

const props = defineProps({
  currentPage: { type: Number, default: 1 },
  totalPages: { type: Number, default: 0 },
  zoom: { type: Number, default: 1.0 },
  rotation: { type: Number, default: 0 },
  pageImageUrl: { type: String, default: null },
  highlights: { type: Array, default: () => [] },
  activeCitationKey: { type: String, default: null },
  status: { type: String, default: null },
  showOverlay: { type: Boolean, default: true },
})

const emit = defineEmits([
  'prev-page',
  'next-page',
  'go-to-page',
  'zoom-in',
  'zoom-out',
  'zoom-reset',
  'rotate-cw',
])

const containerRef = ref(null)
const imageRef = ref(null)

/** CSS display dimensions (computed from container width) */
const displayWidth = ref(800)
const displayHeight = ref(600)

function onImageLoad() {
  if (imageRef.value) {
    displayWidth.value = imageRef.value.naturalWidth || imageRef.value.clientWidth || 800
    displayHeight.value = imageRef.value.naturalHeight || imageRef.value.clientHeight || 600
  }
}

function onPageInput(e) {
  const val = parseInt(e.target.value, 10)
  if (val >= 1 && val <= props.totalPages) {
    emit('go-to-page', val)
  }
  e.target.value = props.currentPage
}

function updateContainerSize() {
  if (containerRef.value) {
    const rect = containerRef.value.getBoundingClientRect()
    // Reserve space for toolbar
    const availableWidth = rect.width - 32
    const availableHeight = rect.height - 56
    if (availableWidth > 100 && availableHeight > 100) {
      displayWidth.value = Math.min(availableWidth, 1200)
      displayHeight.value = Math.min(availableHeight * 0.8, (displayWidth.value * 3) / 4)
    }
  }
}

let resizeObserver = null

onMounted(() => {
  updateContainerSize()
  resizeObserver = new ResizeObserver(() => updateContainerSize())
  if (containerRef.value) {
    resizeObserver.observe(containerRef.value)
  }
})

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
})
</script>

<style scoped>
.ev-page-viewer {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f0f1f3;
}

.ev-viewer-toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.ev-toolbar-group {
  display: flex;
  align-items: center;
  gap: 2px;
}

.ev-toolbar-right {
  margin-left: auto;
}

.ev-toolbar-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
  color: #374151;
  transition: all 0.1s ease;
}

.ev-toolbar-btn:hover:not(:disabled) {
  background: #f3f4f6;
  border-color: #d1d5db;
}

.ev-toolbar-btn:disabled {
  opacity: 0.35;
  cursor: default;
}

.ev-page-indicator {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 13px;
  color: #374151;
  margin: 0 4px;
}

.ev-page-input {
  width: 40px;
  text-align: center;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  padding: 2px 4px;
  font-size: 13px;
  -moz-appearance: textfield;
}

.ev-page-input::-webkit-outer-spin-button,
.ev-page-input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.ev-page-separator {
  color: #9ca3af;
}

.ev-page-total {
  color: #6b7280;
}

.ev-zoom-label,
.ev-rotation-label {
  font-size: 12px;
  color: #6b7280;
  min-width: 36px;
  text-align: center;
}

.ev-page-area {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: auto;
  padding: 16px;
}

.ev-page-container {
  position: relative;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
  border-radius: 2px;
  overflow: hidden;
}

.ev-page-image {
  display: block;
  max-width: 100%;
  height: auto;
}

.ev-page-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
  font-size: 14px;
  min-height: 400px;
}
</style>
