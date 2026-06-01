<template>
  <div class="learning-path-map" v-if="visible">
    <div class="map-header">
      <h3 class="map-title">🗺️ 学习路径</h3>
      <div class="map-actions">
        <button 
          class="toggle-btn" 
          :class="{ active: showDetails }" 
          @click="showDetails = !showDetails"
        >
          {{ showDetails ? '简化视图' : '详细视图' }}
        </button>
        <button class="close-btn" @click="$emit('close')" title="关闭">×</button>
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
            <polygon points="0 0, 10 3.5, 0 7" fill="#6b7280" />
          </marker>
          
          <marker 
            id="arrowhead-jump" 
            markerWidth="10" 
            markerHeight="7" 
            refX="9" 
            refY="3.5" 
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#8b5cf6" />
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
              stroke="#d1d5db"
              stroke-width="2"
              marker-end="url(#arrowhead)"
              stroke-dasharray="5,5"
            />

            <!-- 跳转复习边 -->
            <g v-else-if="edge.type === 'prerequisite_jump'">
              <path
                :d="getJumpEdgePath(edge)"
                :stroke="edge.isReturned ? '#10b981' : '#8b5cf6'"
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
                :fill="edge.isReturned ? '#059669' : '#7c3aed'"
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
              :fill="getNodeColor(node)"
              stroke="#fff"
              stroke-width="3"
              filter="url(#shadow)"
              class="node-circle"
            />

            <!-- 进度环（当前节点） -->
            <circle
              v-if="node.status === 'current' && node.understandingScore !== null"
              r="27"
              fill="none"
              stroke="#e5e7eb"
              stroke-width="4"
            />
            <circle
              v-if="node.status === 'current' && node.understandingScore !== null"
              r="27"
              fill="none"
              stroke="#3b82f6"
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
              :fill="getTextColor(node.status)"
            >
              {{ node.index + 1 }}
            </text>

            <!-- 完成标记 -->
            <text
              v-if="node.status === 'completed'"
              x="12"
              y="-12"
              font-size="18"
            >✓</text>

            <!-- 当前位置指示器 -->
            <circle
              v-if="node.status === 'current'"
              r="30"
              fill="none"
              stroke="#3b82f6"
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
              fill="#374151"
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
              :fill="getUnderstandingColor(node.understandingScore)"
            >
              {{ (node.understandingScore * 100).toFixed(0) }}%
            </text>
          </g>
        </g>
      </svg>

      <!-- 缩放控制 -->
      <div class="zoom-controls">
        <button @click="zoomIn" title="放大">+</button>
        <span class="zoom-level">{{ Math.round(zoom * 100) }}%</span>
        <button @click="zoomOut" title="缩小">−</button>
        <button @click="resetView" title="重置视图" class="reset-btn">⟲</button>
      </div>
    </div>

    <!-- 当前路径说明 -->
    <div class="current-path-info" v-if="pathData.currentPath?.length > 0">
      <h4 class="path-title">📍 当前跳转链</h4>
      <div class="path-chain">
        <template v-for="(step, idx) in pathData.currentPath" :key="idx">
          <div class="path-step" v-if="idx > 0">→</div>
          <div class="path-node" :class="{ returned: step.isReturned }">
            <span class="step-from">{{ step.fromNode }}</span>
            <span class="step-arrow">→</span>
            <span class="step-to">{{ step.toNode }}</span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'

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
      return '#10b981'
    case 'current':
      return '#3b82f6'
    default:
      return '#e5e7eb'
  }
}

function getTextColor(status) {
  return status === 'current' || status === 'completed' ? '#fff' : '#6b7280'
}

function getUnderstandingColor(score) {
  if (score >= 0.85) return '#059669'
  if (score >= 0.7) return '#2563eb'
  if (score >= 0.5) return '#d97706'
  return '#dc2626'
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
  animation: fadeInMap 0.3s ease-out;
}

@keyframes fadeInMap {
  from { opacity: 0; }
  to { opacity: 1; }
}

.map-header {
  padding: 20px 24px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.map-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #111827;
}

.map-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.toggle-btn {
  padding: 8px 16px;
  border: 1px solid #d1d5db;
  background: white;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  color: #374151;
}

.toggle-btn:hover {
  background: #f9fafb;
}

.toggle-btn.active {
  background: #eff6ff;
  border-color: #3b82f6;
  color: #2563eb;
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: #f3f4f6;
  border-radius: 8px;
  font-size: 22px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  color: #6b7280;
}

.close-btn:hover {
  background: #e5e7eb;
  transform: scale(1.05);
}

.statistics-bar {
  display: flex;
  gap: 20px;
  padding: 16px 24px;
  background: #f9fafb;
  border-bottom: 1px solid #e5e7eb;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.stat-number {
  font-size: 20px;
  font-weight: 700;
  color: #111827;
}

.stat-label {
  font-size: 11px;
  color: #6b7280;
  font-weight: 500;
}

.stat-item.success .stat-number { color: #059669; }
.stat-item.warning .stat-number { color: #d97706; }
.stat-item.info .stat-number { color: #2563eb; }

.map-canvas-container {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: #fafafa;
  cursor: grab;
}

.map-canvas-container:active {
  cursor: grabbing;
}

.map-canvas {
  width: 100%;
  height: 100%;
}

.node-group {
  cursor: pointer;
  transition: transform 0.2s;
}

.node-group:hover {
  transform: scale(1.08);
}

.node-circle {
  transition: all 0.3s;
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
  font-weight: 500;
}

.zoom-controls {
  position: absolute;
  bottom: 20px;
  right: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
  background: white;
  padding: 8px 12px;
  border-radius: 10px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.zoom-controls button {
  width: 32px;
  height: 32px;
  border: 1px solid #d1d5db;
  background: white;
  border-radius: 6px;
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.zoom-controls button:hover {
  background: #f3f4f6;
}

.reset-btn {
  margin-left: 8px;
  font-size: 16px !important;
  width: auto !important;
  padding: 0 10px !important;
}

.zoom-level {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
  min-width: 45px;
  text-align: center;
}

.current-path-info {
  padding: 16px 24px;
  background: white;
  border-top: 1px solid #e5e7eb;
}

.path-title {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 600;
  color: #111827;
}

.path-chain {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.path-step {
  color: #9ca3af;
  font-weight: 700;
  font-size: 16px;
}

.path-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: #f3f4f6;
  border-radius: 8px;
  font-size: 13px;
  border: 1px solid #e5e7eb;
}

.path-node.returned {
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #166534;
}

.step-from {
  font-weight: 500;
}

.step-arrow {
  color: #8b5cf6;
  font-weight: 700;
}

.step-to {
  font-weight: 600;
  color: #7c3aed;
}
</style>