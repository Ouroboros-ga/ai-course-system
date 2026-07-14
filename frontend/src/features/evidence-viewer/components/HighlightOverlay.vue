<template>
  <div class="ev-highlight-overlay" aria-hidden="true">
    <!-- Bounding box highlights -->
    <div
      v-for="(hl, idx) in overlayRects"
      :key="`bbox-${idx}`"
      class="ev-highlight-rect"
      :style="{
        left: hl.x + 'px',
        top: hl.y + 'px',
        width: hl.w + 'px',
        height: hl.h + 'px',
        background: hl.color,
        borderColor: hl.borderColor,
      }"
    ></div>

    <!-- SVG polygon highlights -->
    <svg
      class="ev-highlight-svg"
      :width="displayWidth"
      :height="displayHeight"
      v-if="polygonPaths.length > 0"
    >
      <polygon
        v-for="(poly, idx) in polygonPaths"
        :key="`poly-${idx}`"
        :points="poly.points"
        :fill="poly.color"
        :stroke="poly.borderColor"
        stroke-width="1.5"
        fill-opacity="0.35"
      />
    </svg>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  bboxToDisplayRect,
  polygonToDisplayPoints,
} from '../composables/coordinateTransform.js'

const props = defineProps({
  /**
   * Array of highlight objects, each with:
   *   { bboxes, polygons, color, status, key }
   */
  highlights: { type: Array, default: () => [] },
  /** Current CSS display dimensions */
  displayWidth: { type: Number, default: 800 },
  displayHeight: { type: Number, default: 600 },
  /** Current zoom level */
  zoom: { type: Number, default: 1.0 },
  /** Current rotation in degrees */
  rotation: { type: Number, default: 0 },
  /** Only show highlights for a specific citation key (null = show all) */
  activeKey: { type: String, default: null },
})

/**
 * Compute overlay rectangles from bboxes.
 */
const overlayRects = computed(() => {
  const results = []

  for (const hl of props.highlights) {
    // If activeKey is set, only show that citation's highlights
    if (props.activeKey && hl.key !== props.activeKey) continue

    const color = hl.color || 'rgba(34, 197, 94, 0.25)'
    const borderColor = color.replace('0.25', '0.6').replace('0.35', '0.7').replace('0.4', '0.8')

    for (const bb of (hl.bboxes || [])) {
      const rect = bboxToDisplayRect(bb, props.displayWidth, props.displayHeight, {
        zoom: props.zoom,
        rotation: props.rotation,
      })
      if (rect) {
        results.push({
          x: rect.x,
          y: rect.y,
          w: rect.w,
          h: rect.h,
          color,
          borderColor,
        })
      }
    }
  }

  return results
})

/**
 * Compute SVG polygon paths.
 */
const polygonPaths = computed(() => {
  const results = []

  for (const hl of props.highlights) {
    if (props.activeKey && hl.key !== props.activeKey) continue

    const color = hl.color || 'rgba(34, 197, 94, 0.25)'
    const borderColor = color.replace('0.25', '0.6').replace('0.35', '0.7').replace('0.4', '0.8')

    for (const poly of (hl.polygons || [])) {
      const points = polygonToDisplayPoints(poly, props.displayWidth, props.displayHeight, {
        zoom: props.zoom,
        rotation: props.rotation,
      })
      if (points) {
        results.push({ points, color, borderColor })
      }
    }
  }

  return results
})
</script>

<style scoped>
.ev-highlight-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 10;
}

.ev-highlight-rect {
  position: absolute;
  border: 2px solid;
  border-radius: 2px;
  pointer-events: none;
  box-sizing: border-box;
}

.ev-highlight-svg {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
}
</style>
