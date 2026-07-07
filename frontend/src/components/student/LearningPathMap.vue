<template>
  <div class="learning-path-map" v-if="visible">
    <div class="map-header">
      <h3 class="map-title"><Map :size="20" /> 学习路径</h3>
      <div class="map-actions">
        <button
          class="toggle-btn"
          :class="{ active: showDetails }"
          @click="showDetails = !showDetails"
        >
          {{ showDetails ? '简化视图' : '详细视图' }}
        </button>
        <button class="close-btn" @click="$emit('close')" title="关闭"><X :size="20" /></button>
      </div>
    </div>

    <div class="statistics-bar" v-if="pathData.statistics">
      <div class="stat-item">
        <span class="stat-number">{{ pathData.statistics.totalJumps }}</span>
        <span class="stat-label">总跳转次数</span>
      </div>
      <div class="stat-item success">
        <span class="stat-number">{{ pathData.statistics.completedJumps }}</span>
        <span class="stat-label">已完成复习</span>
      </div>
      <div class="stat-item warning">
        <span class="stat-number">{{ pathData.statistics.pendingJumps }}</span>
        <span class="stat-label">待完成</span>
      </div>
      <div class="stat-item info">
        <span class="stat-number">{{ pathData.statistics.avgReviewTime }}</span>
        <span class="stat-label">平均复习时长</span>
      </div>
    </div>

    <div class="map-canvas-container">
      <svg
        ref="canvasRef"
        :viewBox="`0 0 ${canvasWidth} ${canvasHeight}`"
        class="map-canvas"
        @wheel="handleZoom"
        @mousedown="startDrag"
        @mousemove="onDrag"
        @mouseup="endDrag"
        @mouseleave="endDrag"
      >
        <defs>
          <marker
            id="arrowhead"
            markerWidth="10"
            markerHeight="7"
            refX="9"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" class="marker-arrow-default" />
          </marker>

          <marker
            id="arrowhead-jump"
            markerWidth="10"
            markerHeight="7"
            refX="9"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" class="marker-arrow-jump" />
          </marker>

          <filter id="shadow">
            <feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity="0.15"/>
          </filter>

          <filter id="glow-jump">
            <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
            <feMerge>
              <feMergeNode in="coloredBlur"/>
              <feMergeNode in="SourceGraphic"/>
            </feMerge>
          </filter>
        </defs>

        <g :transform="`translate(${pan.x}, ${pan.y}) scale(${zoom})`">
          <!-- 边（连接线） -->
          <g v-for="(edge, index) in edges" :key="'edge-' + index">
            <!-- 学习顺序边 -->
            <line
              v-if="edge.type === 'learning_order'"
              :x1="getNodePosition(edge.from).x"
              :y1="getNodePosition(edge.from).y"
              :x2="getNodePosition(edge.to).y ? getNodePosition(edge.to).x : 1000"
              :y2="getNodePosition(edge.to).y || 100"
              class="learning-edge"
              stroke-width="2"
              marker-end="url(#arrowhead)"
              stroke-dasharray="5,5"
            />

            <!-- 跳转复习边 -->
            <g v-else-if="edge.type === 'prerequisite_jump'">
              <path
                :d="getJumpEdgePath(edge)"
                :style="{ stroke: edge.isReturned ? 'var(--color-success)' : 'var(--color-secondary)' }"
                stroke-width="3"
                fill="none"
                :marker-end="edge.isReturned ? '' : 'url(#arrowhead-jump)'"
                :stroke-dasharray="edge.isReturned ? 'none' : '8,4'"
                :opacity="edge.isReturned ? 0.6 : 1"
                :filter="!edge.isReturned ? 'url(#glow-jump)' : ''"
                class="jump-edge"
              />

              <text
                :x="getJumpEdgeMidpoint(edge).x"
                :y="getJumpEdgeMidpoint(edge).y - 8"
                text-anchor="middle"
                font-size="11"
                :style="{ fill: edge.isReturned ? 'var(--color-success)' : 'var(--color-secondary)' }"
                class="edge-label"
                v-if="showDetails && zoom > 0.8"
              >
                {{ edge.label?.slice(0, 20) }}{{ edge.label?.length > 20 ? '...' : '' }}
              </text>
            </g>
          </g>

          <!-- 节点 -->
          <g
            v-for="node in nodes"
            :key="'node-' + node.id"
            :transform="`translate(${getNodePosition(node.id).x}, ${getNodePosition(node.id).y})`"
            class="node-group"
            :class="{ 'current': node.status === 'current', 'completed': node.status === 'completed' }"
            @click="$emit('node-click', node)"
          >
            <!-- 节点圆圈 -->
            <circle
              r="24"
              :style="{ fill: getNodeColor(node), stroke: 'var(--color-text-inverse)' }"
              stroke-width="3"
              filter="url(#shadow)"
              class="node-circle"
            />

            <!-- 进度环（当前节点） -->
            <circle
              v-if="node.status === 'current' && node.understandingScore !== null"
              r="27"
              fill="none"
              style="stroke: var(--color-border)"
              stroke-width="4"
            />
            <circle
              v-if="node.status === 'current' && node.understandingScore !== null"
              r="27"
              fill="none"
              style="stroke: var(--color-primary)"
              stroke-width="4"
              :stroke-dasharray="`${node.understandingScore * 169} 169`"
              transform="rotate(-90)"
              opacity="0.8"
            />

            <!-- 节点图标/序号 -->
            <text
              text-anchor="middle"
              dominant-baseline="central"
              :font-size="node.status === 'current' ? '16' : '14'"
              :font-weight="node.status === 'current' ? '700' : '600'"
              :style="{ fill: getTextColor(node.status) }"
            >
              {{ node.index + 1 }}
            </text>

            <!-- 完成标记 -->
            <g v-if="node.status === 'completed'" transform="translate(12, -12)">
              <circle r="7" style="fill: var(--color-success)" />
              <path d="M-3 0l2 2l4-4" style="stroke: var(--color-text-inverse)" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" />
            </g>

            <!-- 当前位置指示器 -->
            <circle
              v-if="node.status === 'current'"
              r="30"
              fill="none"
              style="stroke: var(--color-primary)"
              stroke-width="2"
              opacity="0.5"
              class="pulse-ring"
            />

            <!-- 节点标题 -->
            <text
              v-if="showDetails && zoom > 0.7"
              y="38"
              text-anchor="middle"
              font-size="11"
              style="fill: var(--color-text-secondary)"
              font-weight="500"
              class="node-title"
            >
              {{ truncateText(node.title, 12) }}
            </text>

            <!-- 理解度显示 -->
            <text
              v-if="showDetails && node.understandingScore !== null && zoom > 0.8"
              y="52"
              text-anchor="middle"
              font-size="10"
              :style="{ fill: getUnderstandingColor(node.understandingScore) }"
            >
              {{ (node.understandingScore * 100).toFixed(0) }}%
            </text>
          </g>
        </g>
      </svg>

      <!-- 缩放控制 -->
      <div class="zoom-controls">
        <button @click="zoomIn" title="放大"><Plus :size="18" /></button>
        <span class="zoom-level">{{ Math.round(zoom * 100) }}%</span>
        <button @click="zoomOut" title="缩小"><Minus :size="18" /></button>
        <button @click="resetView" title="重置视图" class="reset-btn"><RotateCcw :size="16" /></button>
      </div>
    </div>

    <!-- 当前路径说明 -->
    <div class="current-path-info" v-if="pathData.currentPath?.length > 0">
      <h4 class="path-title"><MapPin :size="16" /> 当前跳转链</h4>
      <div class="path-chain">
        <template v-for="(step, idx) in pathData.currentPath" :key="idx">
          <div class="path-step" v-if="idx > 0"><ArrowRight :size="16" /></div>
          <div class="path-node" :class="{ returned: step.isReturned }">
            <span class="step-from">{{ step.fromNode }}</span>
            <span class="step-arrow"><ArrowRight :size="14" /></span>
            <span class="step-to">{{ step.toNode }}</span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Map, X, MapPin, ArrowRight, Plus, Minus, RotateCcw } from 'lucide-vue-next'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false,
  },
  pathData: {
    type: Object,
    default: () => ({
      nodes: [],
      edges: [],
      currentPath: [],
      statistics: null,
    }),
  },
})

const emit = defineEmits(['close', 'node-click'])

const canvasRef = ref(null)
const canvasWidth = ref(800)
const canvasHeight = ref(600)

const zoom = ref(1)
const pan = ref({ x: 0, y: 0 })
const isDragging = ref(false)
const dragStart = ref({ x: 0, y: 0 })

const showDetails = ref(true)

const nodes = computed(() => props.pathData.nodes || [])
const edges = computed(() => props.pathData.edges || [])

function getNodePosition(nodeId) {
  const node = nodes.value.find(n => n.id === nodeId)
  if (!node) return { x: 0, y: 0 }

  const cols = 5
  const spacingX = 140
  const spacingY = 120

  const col = (node.index || 0) % cols
  const row = Math.floor((node.index || 0) / cols)

  return {
    x: 80 + col * spacingX,
    y: 80 + row * spacingY,
  }
}

function getNodeColor(node) {
  switch (node.status) {
    case 'completed':
      return 'var(--color-success)'
    case 'current':
      return 'var(--color-primary)'
    default:
      return 'var(--color-border)'
  }
}

function getTextColor(status) {
  return status === 'current' || status === 'completed' ? 'var(--color-text-inverse)' : 'var(--color-text-secondary)'
}

function getUnderstandingColor(score) {
  if (score >= 0.85) return 'var(--color-success)'
  if (score >= 0.7) return 'var(--color-primary)'
  if (score >= 0.5) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

function getJumpEdgePath(edge) {
  const fromPos = getNodePosition(edge.from)
  const toPos = getNodePosition(edge.to)

  if (!fromPos.x || !toPos.x) return ''

  const midX = (fromPos.x + toPos.x) / 2
  const midY = (fromPos.y + toPos.y) / 2 - 40

  return `M ${fromPos.x} ${fromPos.y} Q ${midX} ${midY} ${toPos.x} ${toPos.y}`
}

function getJumpEdgeMidpoint(edge) {
  const fromPos = getNodePosition(edge.from)
  const toPos = getNodePosition(edge.to)

  return {
    x: (fromPos.x + toPos.x) / 2,
    y: (fromPos.y + toPos.y) / 2 - 40,
  }
}

function truncateText(text, maxLength) {
  if (!text) return ''
  return text.length > maxLength ? text.slice(0, maxLength) + '...' : text
}

function handleZoom(e) {
  e.preventDefault()
  const delta = e.deltaY > 0 ? -0.1 : 0.1
  const newZoom = Math.max(0.3, Math.min(3, zoom.value + delta))
  zoom.value = newZoom
}

function zoomIn() {
  zoom.value = Math.min(3, zoom.value + 0.2)
}

function zoomOut() {
  zoom.value = Math.max(0.3, zoom.value - 0.2)
}

function resetView() {
  zoom.value = 1
  pan.value = { x: 0, y: 0 }
}

function startDrag(e) {
  isDragging.value = true
  dragStart.value = { x: e.clientX - pan.value.x, y: e.clientY - pan.value.y }
}

function onDrag(e) {
  if (!isDragging.value) return
  pan.value = {
    x: e.clientX - dragStart.value.x,
    y: e.clientY - dragStart.value.y,
  }
}

function endDrag() {
  isDragging.value = false
}

watch(() => props.visible, (newVal) => {
  if (newVal) {
    updateCanvasSize()
  }
})

function updateCanvasSize() {
  if (nodes.value.length > 0) {
    const cols = 5
    const rows = Math.ceil(nodes.value.length / cols)
    canvasWidth.value = Math.max(800, cols * 140 + 160)
    canvasHeight.value = Math.max(600, rows * 120 + 200)
  }
}

onMounted(() => {
  updateCanvasSize()
})
</script>

<style scoped>
.learning-path-map {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.98);
  z-index: 9998;
  display: flex;
  flex-direction: column;
  animation: fadeInMap var(--duration-slow) var(--ease);
}

@keyframes fadeInMap {
  from { opacity: 0; }
  to { opacity: 1; }
}

.map-header {
  padding: 20px var(--space-5);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.map-title {
  margin: 0;
  font-size: var(--text-xl);
  font-weight: var(--font-bold);
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.map-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.toggle-btn {
  padding: var(--space-2) var(--space-4);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  border-radius: var(--radius-md);
  font-size: 13px;
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease);
  color: var(--color-text-secondary);
}

.toggle-btn:hover {
  background: var(--color-bg);
}

.toggle-btn.active {
  background: var(--color-primary-light);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.close-btn {
  width: var(--space-6);
  height: var(--space-6);
  border: none;
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--duration-normal) var(--ease);
  color: var(--color-text-secondary);
}

.close-btn:hover {
  background: var(--color-border);
  transform: translateY(-2px);
}

.statistics-bar {
  display: flex;
  gap: 20px;
  padding: var(--space-4) var(--space-5);
  background: var(--color-bg);
  border-bottom: 1px solid var(--color-border);
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
}

.stat-number {
  font-size: var(--text-xl);
  font-weight: var(--font-bold);
  color: var(--color-text);
}

.stat-label {
  font-size: 11px;
  color: var(--color-text-secondary);
  font-weight: var(--font-medium);
}

.stat-item.success .stat-number { color: var(--color-success); }
.stat-item.warning .stat-number { color: var(--color-warning); }
.stat-item.info .stat-number { color: var(--color-primary); }

.map-canvas-container {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: var(--color-bg);
  cursor: grab;
}

.map-canvas-container:active {
  cursor: grabbing;
}

.map-canvas {
  width: 100%;
  height: 100%;
}

.marker-arrow-default { fill: var(--color-text-secondary); }
.marker-arrow-jump { fill: var(--color-secondary); }
.learning-edge { stroke: var(--color-border); }

.node-group {
  cursor: pointer;
  transition: transform var(--duration-normal) var(--ease);
}

.node-group:hover {
  transform: translateY(-2px);
}

.node-circle {
  transition: all var(--duration-slow) var(--ease);
}

.pulse-ring {
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 0.5; r: 30; }
  50% { opacity: 0.2; r: 35; }
}

.jump-edge {
  animation: dashMove 1s linear infinite;
}

@keyframes dashMove {
  to { stroke-dashoffset: -12; }
}

.edge-label {
  font-weight: var(--font-medium);
}

.zoom-controls {
  position: absolute;
  bottom: 20px;
  right: 20px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  background: var(--color-surface);
  padding: var(--space-2) var(--space-3);
  border-radius: 10px;
  box-shadow: var(--shadow-md);
}

.zoom-controls button {
  width: var(--space-6);
  height: var(--space-6);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  border-radius: var(--radius-sm);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--duration-normal) var(--ease);
}

.zoom-controls button:hover {
  background: var(--color-surface-2);
}

.reset-btn {
  margin-left: var(--space-2);
  width: auto !important;
  padding: 0 10px !important;
}

.zoom-level {
  font-size: 12px;
  font-weight: var(--font-semibold);
  color: var(--color-text-secondary);
  min-width: 45px;
  text-align: center;
}

.current-path-info {
  padding: var(--space-4) var(--space-5);
  background: var(--color-surface);
  border-top: 1px solid var(--color-border);
}

.path-title {
  margin: 0 0 var(--space-3);
  font-size: 15px;
  font-weight: var(--font-semibold);
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.path-chain {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.path-step {
  display: flex;
  align-items: center;
  color: var(--color-text-muted);
  font-weight: var(--font-bold);
  font-size: var(--text-base);
}

.path-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: var(--space-2) 14px;
  background: var(--color-surface-2);
  border-radius: var(--radius-md);
  font-size: 13px;
  border: 1px solid var(--color-border);
}

.path-node.returned {
  background: var(--color-success-light);
  border-color: var(--color-success-light);
  color: var(--color-success);
}

.step-from {
  font-weight: var(--font-medium);
}

.step-arrow {
  display: inline-flex;
  align-items: center;
  color: var(--color-secondary);
  font-weight: var(--font-bold);
}

.step-to {
  font-weight: var(--font-semibold);
  color: var(--color-secondary);
}
</style>
