<template>
  <div
    class="mind-map-wrapper"
    ref="wrapperRef"
    @wheel="handleWheel"
    @mousedown="handleMouseDown"
    @mousemove="handleMouseMove"
    @mouseup="handleMouseUp"
    @mouseleave="handleMouseUp"
  >
    <!-- 缩放平移容器 -->
    <div
      class="mind-map-canvas"
      :style="{ transform: `scale(${scale}) translate(${translateX}px, ${translateY}px)` }"
    >
      <!-- SVG 连接线层 -->
      <svg class="links-layer" :width="svgWidth" :height="svgHeight">
        <path
          v-for="(link, index) in links"
          :key="index"
          :d="link.d"
          class="link-path"
        />
      </svg>

      <!-- 节点层 -->
      <div
        v-for="node in nodes"
        :key="node.id"
        class="node-item"
        :class="{ 'is-root': node.isRoot }"
        :style="{ left: node.x + 'px', top: node.y + 'px' }"
      >
        <div class="node-content">
          {{ node.name }}
        </div>
      </div>
    </div>

    <!-- 缩放控件 -->
    <div class="zoom-controls">
      <button @click="zoomIn">+</button>
      <span>{{ Math.round(scale * 100) }}%</span>
      <button @click="zoomOut">−</button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  data: {
    type: Object,
    required: true
  }
})

// --- 状态管理 ---
const wrapperRef = ref(null)
const scale = ref(1)
const translateX = ref(0)
const translateY = ref(0)

// 拖拽状态
const isDragging = ref(false)
const dragStartX = ref(0)
const dragStartY = ref(0)
const dragStartTranslateX = ref(0)
const dragStartTranslateY = ref(0)

// 节点与连线数据
const nodes = ref([])
const links = ref([])

// 画布尺寸
const svgWidth = ref(2000)
const svgHeight = ref(1500)

// 配置项
const config = {
  nodeWidth: 120,
  nodeHeight: 40,
  horizontalSpacing: 80,
  verticalSpacing: 20,
  startX: 100,
  startY: 100
}

// 【重要】布局计算变量，必须在此处初始化
let currentY = config.startY

// --- 布局算法 ---
const calculateLayout = (data) => {
  const nodeList = []
  const linkList = []

  // 重置Y坐标计数器
  currentY = config.startY

  function traverse(node, depth, parentId) {
    const x = config.startX + depth * (config.nodeWidth + config.horizontalSpacing)

    // 兼容多种属性名：name / label / text
    const nodeName = node.name || node.label || node.text || '未命名'

    const nodeData = {
      id: nodeName + depth + Math.random(),
      name: nodeName,
      x: x,
      y: currentY,
      isRoot: depth === 0,
      childrenCount: node.children ? node.children.length : 0
    }

    nodeList.push(nodeData)
    currentY += config.nodeHeight + config.verticalSpacing

    if (parentId !== null) {
      const parent = nodeList.find(n => n.id === parentId)
      if (parent) {
        linkList.push(createLinkPath(parent, nodeData))
      }
    }

    if (node.children && node.children.length > 0) {
      node.children.forEach(child => {
        traverse(child, depth + 1, nodeData.id)
      })
    }
  }

  traverse(data, 0, null)

  if (nodeList.length > 0) {
      const maxY = Math.max(...nodeList.map(n => n.y))
      const maxX = Math.max(...nodeList.map(n => n.x))
      svgHeight.value = maxY + 200
      svgWidth.value = maxX + 400
  }

  return { nodeList, linkList }
}

// 生成贝塞尔曲线路径
const createLinkPath = (source, target) => {
  const sx = source.x + config.nodeWidth
  const sy = source.y + config.nodeHeight / 2
  const tx = target.x
  const ty = target.y + config.nodeHeight / 2
  const midX = sx + (tx - sx) / 2
  const d = `M ${sx} ${sy} C ${midX} ${sy}, ${midX} ${ty}, ${tx} ${ty}`
  return { d }
}

// --- 缩放逻辑 ---
const handleWheel = (e) => {
  e.preventDefault()
  const zoomSpeed = 0.05
  if (e.deltaY < 0) {
    scale.value = Math.min(scale.value + zoomSpeed, 2)
  } else {
    scale.value = Math.max(scale.value - zoomSpeed, 0.2)
  }
}

const zoomIn = () => { scale.value = Math.min(scale.value + 0.1, 2) }
const zoomOut = () => { scale.value = Math.max(scale.value - 0.1, 0.2) }

// --- 拖拽移动逻辑 ---
const handleMouseDown = (e) => {
  // 只响应左键
  if (e.button !== 0) return

  isDragging.value = true
  dragStartX.value = e.clientX
  dragStartY.value = e.clientY
  // 记录开始拖拽时的偏移量
  dragStartTranslateX.value = translateX.value
  dragStartTranslateY.value = translateY.value

  // 设置拖拽时的鼠标样式（全局）
  document.body.style.cursor = 'grabbing'
}

const handleMouseMove = (e) => {
  if (!isDragging.value) return

  // 计算鼠标移动的距离
  const dx = e.clientX - dragStartX.value
  const dy = e.clientY - dragStartY.value

  // 更新画布偏移量
  // 注意：因为 transform 中 translate 是在 scale 之后（或之前，取决于CSS写法），
  // 这里我们直接累加，在 scale(1) 时是 1:1 移动的。
  // 如果在 scale 缩放下，视觉移动距离 = 鼠标移动距离。
  translateX.value = dragStartTranslateX.value + dx
  translateY.value = dragStartTranslateY.value + dy
}

const handleMouseUp = () => {
  isDragging.value = false
  // 恢复默认鼠标样式
  document.body.style.cursor = ''
}

// --- 监听数据变化 ---
watch(() => props.data, (newData) => {
  if (newData) {
    const result = calculateLayout(newData)
    nodes.value = result.nodeList
    links.value = result.linkList
  }
}, { immediate: true, deep: true })

</script>

<style scoped>
.mind-map-wrapper {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--color-surface);
  /* 点阵背景 */
  background-image:
    radial-gradient(var(--color-border) 1px, transparent 1px);
  background-size: 20px 20px;
  cursor: grab; /* 默认抓手图标 */
  user-select: none; /* 防止拖拽时选中文字 */
}

/* 拖拽时的按下状态 */
.mind-map-wrapper:active {
  cursor: grabbing;
}

.mind-map-canvas {
  position: absolute;
  top: 0;
  left: 0;
  transform-origin: 0 0;
  transition: transform 0.1s ease-out;
  /* 使拖拽更流畅 */
  will-change: transform;
}

.links-layer {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
}

.link-path {
  fill: none;
  stroke: var(--color-primary-light);
  stroke-width: 2px;
  stroke-linecap: round;
}

.node-item {
  position: absolute;
  width: 120px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-surface);
  border-radius: 8px;
  border: 2px solid var(--color-primary-light);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  transition: all 0.2s ease;
  /* 防止拖拽时选中节点文字 */
  pointer-events: none; /* 暂时设为none防止阻碍拖拽，后续如需节点点击事件需改回auto并在mousedown阻止冒泡 */
}

.node-item:hover {
  border-color: var(--color-primary);
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.15);
  transform: translateY(-2px);
  z-index: 10;
}

.node-item.is-root {
  width: 140px;
  height: 50px;
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-secondary) 100%);
  border: none;
  color: var(--color-text-inverse);
  font-weight: bold;
  font-size: 15px;
  box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3);
}

.node-item.is-root:hover {
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4);
}

.node-content {
  padding: 0 10px;
  text-align: center;
  font-size: 13px;
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.is-root .node-content {
  color: var(--color-text-inverse);
}

.zoom-controls {
  position: absolute;
  bottom: 20px;
  right: 20px;
  background: var(--color-surface);
  padding: 6px 12px;
  border-radius: 20px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.1);
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--color-text-secondary);
  user-select: none;
  z-index: 100;
}

.zoom-controls button {
  background: var(--color-surface-2);
  border: none;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  cursor: pointer;
  font-weight: bold;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
}

.zoom-controls button:hover {
  background: var(--color-border);
}
</style>
